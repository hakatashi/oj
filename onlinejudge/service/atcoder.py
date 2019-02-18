# Python Version: 3.x
# -*- coding: utf-8 -*-
import datetime
import itertools
import json
import posixpath
import re
import urllib.parse
from typing import *

import bs4
import requests

import onlinejudge.dispatch
import onlinejudge.implementation.logging as log
import onlinejudge.implementation.utils as utils
import onlinejudge.type
from onlinejudge.type import SubmissionError


# This is a workaround. AtCoder's servers sometime fail to send "Content-Type" field.
# see https://github.com/kmyk/online-judge-tools/issues/28 and https://github.com/kmyk/online-judge-tools/issues/232
def _request(*args, **kwargs):
    resp = utils.request(*args, **kwargs)
    log.debug('AtCoder\'s server said "Content-Type: %s"', resp.headers.get('Content-Type', '(not sent)'))
    resp.encoding = 'UTF-8'
    return resp


@utils.singleton
class AtCoderService(onlinejudge.type.Service):
    def login(self, get_credentials: onlinejudge.type.CredentialsProvider, session: Optional[requests.Session] = None) -> bool:
        session = session or utils.new_default_session()
        url = 'https://practice.contest.atcoder.jp/login'
        # get
        resp = _request('GET', url, session=session, allow_redirects=False)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        for msg in msgs:
            log.status('message: %s', msg)
        if msgs:
            return 'login' not in resp.url
        # post
        username, password = get_credentials()
        resp = _request('POST', url, session=session, data={'name': username, 'password': password}, allow_redirects=False)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        AtCoderService._report_messages(msgs)
        return 'login' not in resp.url  # AtCoder redirects to the top page if success

    def is_logged_in(self, session: Optional[requests.Session] = None) -> bool:
        session = session or utils.new_default_session()
        url = 'https://practice.contest.atcoder.jp/login'
        resp = _request('GET', url, session=session, allow_redirects=False)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        return bool(msgs)

    def get_url(self) -> str:
        return 'https://atcoder.jp/'

    def get_name(self) -> str:
        return 'atcoder'

    @classmethod
    def from_url(cls, s: str) -> Optional['AtCoderService']:
        # example: https://atcoder.jp/
        # example: http://agc012.contest.atcoder.jp/
        result = urllib.parse.urlparse(s)
        if result.scheme in ('', 'http', 'https') \
                and (result.netloc in ('atcoder.jp', 'beta.atcoder.jp') or result.netloc.endswith('.contest.atcoder.jp')):
            return cls()
        return None

    @classmethod
    def _get_messages_from_cookie(cls, cookies) -> List[str]:
        msgtags = []  # type: List[str]
        for cookie in cookies:
            log.debug('cookie: %s', str(cookie))
            if cookie.name.startswith('__message_'):
                msg = json.loads(urllib.parse.unquote_plus(cookie.value))
                msgtags += [msg['c']]
                log.debug('message: %s: %s', cookie.name, str(msg))
        msgs = []  # type: List[str]
        for msgtag in msgtags:
            soup = bs4.BeautifulSoup(msgtag, utils.html_parser)
            msg = None
            for tag in soup.find_all():
                if tag.string and tag.string.strip():
                    msg = tag.string
                    break
            if msg is None:
                log.error('failed to parse message')
            else:
                msgs += [msg]
        return msgs

    @classmethod
    def _report_messages(cls, msgs: List[str], unexpected: bool = False) -> bool:
        for msg in msgs:
            log.status('message: %s', msg)
        if msgs and unexpected:
            log.failure('unexpected messages found')
        return bool(msgs)

    def iterate_contests(self, lang: str = 'ja', session: Optional[requests.Session] = None) -> Generator['AtCoderContest', None, None]:
        assert lang in ('ja', 'en')  # NOTE: "lang=ja" is required to see some Japanese-local contests. However you can use "lang=en" to see the English names of contests.
        session = session or utils.new_default_session()
        last_page = None
        for page in itertools.count(1):  # 1-based
            if last_page is not None and page > last_page:
                break
            # get
            url = 'https://atcoder.jp/contests/archive?lang={}&page={}'.format(lang, page)
            resp = _request('GET', url, session=session)
            # parse
            soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
            if last_page is None:
                last_page = int(soup.find('ul', class_='pagination').find_all('li')[-1].text)
                log.debug('last page: %s', last_page)
            tbody = soup.find('tbody')
            for tr in tbody.find_all('tr'):
                yield AtCoderContest._from_table_row(tr, lang=lang)

    def get_user_history_url(self, user_id: str) -> str:
        return 'https://atcoder.jp/users/{}/history/json'.format(user_id)


class AtCoderContest(object):
    def __init__(self, contest_id: str):
        self.contest_id = contest_id

        # NOTE: some fields remain undefined, comparing `_from_table_row`
        self._start_time_url = None  # type: Optional[str]
        self._contest_name_ja = None  # type: Optional[str]
        self._contest_name_en = None  # type: Optional[str]
        self._duration_text = None  # type: Optional[str]
        self._rated_range = None  # type: Optional[str]

    @classmethod
    def from_url(cls, url: str) -> Optional['AtCoderContest']:
        result = urllib.parse.urlparse(url)

        # example: https://kupc2014.contest.atcoder.jp/tasks/kupc2014_d
        if result.scheme in ('', 'http', 'https') and result.hostname.endswith('.contest.atcoder.jp'):
            contest_id = utils.remove_suffix(result.hostname, '.contest.atcoder.jp')
            return cls(contest_id)

        # example: https://atcoder.jp/contests/agc030
        if result.scheme in ('', 'http', 'https') and result.hostname in ('atcoder.jp', 'beta.atcoder.jp'):
            m = re.match(r'^/contests/([\w\-_]+)/?$', utils.normpath(result.path))
            if m:
                contest_id = m.group(1)
                return cls(contest_id)

        return None

    @classmethod
    def _from_table_row(cls, tr: bs4.Tag, lang: str) -> 'AtCoderContest':
        tds = tr.find_all('td')
        assert len(tds) == 4
        anchors = [tds[0].find('a'), tds[1].find('a')]
        contest_path = anchors[1]['href']
        assert contest_path.startswith('/contests/')
        contest_id = contest_path[len('/contests/'):]
        self = AtCoderContest(contest_id)
        self._start_time_url = anchors[0]['href']
        if lang == 'ja':
            self._contest_name_ja = anchors[1].text
        elif lang == 'en':
            self._contest_name_en = anchors[1].text
        else:
            assert False
        self._duration_text = tds[2].text
        self._rated_range = tds[3].text
        return self

    def get_start_time(self) -> datetime.datetime:
        if self._start_time_url is None:
            raise NotImplementedError
        # TODO: we need to use an ISO-format parser
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self._start_time_url).query)
        assert len(query['iso']) == 1
        assert query['p1'] == ['248']  # means JST
        return datetime.datetime.strptime(query['iso'][0], '%Y%m%dT%H%M').replace(tzinfo=utils.tzinfo_jst)

    def get_contest_name(self, lang: Optional[str] = None) -> str:
        if lang is None:
            if self._contest_name_en is not None:
                return self._contest_name_en
            elif self._contest_name_ja is not None:
                return self._contest_name_ja
            else:
                raise NotImplementedError
        elif lang == 'en':
            if self._contest_name_en is None:
                raise NotImplementedError
            return self._contest_name_en
        elif lang == 'ja':
            if self._contest_name_ja is None:
                raise NotImplementedError
            return self._contest_name_ja
        else:
            assert False

    def get_duration(self) -> datetime.timedelta:
        if self._duration_text is None:
            raise NotImplementedError
        hours, minutes = map(int, self._duration_text.split(':'))
        return datetime.timedelta(hours=hours, minutes=minutes)

    def get_rated_range(self) -> str:
        if self._rated_range is None:
            raise NotImplementedError
        return self._rated_range

    def list_problems(self, session: Optional[requests.Session] = None) -> List['AtCoderProblem']:
        # get
        session = session or utils.new_default_session()
        url = 'https://atcoder.jp/contests/{}/tasks'.format(self.contest_id)
        resp = _request('GET', url, session=session)

        # parse
        soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
        tbody = soup.find('tbody')
        return [AtCoderProblem._from_table_row(tr) for tr in tbody.find_all('tr')]


class AtCoderProblem(onlinejudge.type.Problem):
    # AtCoder has problems independently from contests. Therefore the notions "contest_id", "alphabet", and "url" don't belong to problems itself.

    def __init__(self, contest_id: str, problem_id: str):
        self.contest_id = contest_id
        self.problem_id = problem_id  # TODO: fix the name, since AtCoder calls this as "task_screen_name"
        self._task_id = None  # type: Optional[int]
        self._task_name = None  # type: Optional[str]
        self._time_limit_msec = None  # type: Optional[int]
        self._memory_limit_mb = None  # type: Optional[int]
        self._alphabet = None  # type: Optional[str]

    @classmethod
    def _from_table_row(cls, tr: bs4.Tag) -> 'AtCoderProblem':
        tds = tr.find_all('td')
        assert len(tds) == 5
        path = tds[1].find('a')['href']
        self = cls.from_url('https://atcoder.jp/' + path)
        assert self is not None
        self._alphabet = tds[0].text
        self._task_name = tds[1].text
        self._time_limit_msec = int(float(utils.remove_suffix(tds[2].text, ' sec')) * 1000)
        self._memory_limit_mb = int(utils.remove_suffix(tds[3].text, ' MB'))
        assert tds[4].text.strip() in ('', 'Submit')
        return self

    def download_sample_cases(self, session: Optional[requests.Session] = None) -> List[onlinejudge.type.TestCase]:
        session = session or utils.new_default_session()
        # get
        resp = _request('GET', self.get_url(), session=session)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        if AtCoderService._report_messages(msgs, unexpected=True):
            # example message: "message: You cannot see this page."
            log.warning('are you logged in?')
            return []
        # parse
        soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
        samples = utils.SampleZipper()
        lang = None
        for pre, h3 in self._find_sample_tags(soup):
            s = utils.textfile(utils.dos2unix(pre.string.lstrip()))
            name = h3.string
            l = self._get_tag_lang(pre)
            if lang is None:
                lang = l
            elif lang != l:
                log.info('skipped due to language: current one is %s, not %s: %s ', lang, l, name)
                continue
            samples.add(s, name)
        return samples.get()

    def _get_tag_lang(self, tag):
        assert isinstance(tag, bs4.Tag)
        for parent in tag.parents:
            for cls in parent.attrs.get('class') or []:
                if cls.startswith('lang-'):
                    return cls

    def _find_sample_tags(self, soup) -> Generator[Tuple[bs4.Tag, bs4.Tag], None, None]:
        for pre in soup.find_all('pre'):
            log.debug('pre tag: %s', str(pre))
            if not pre.string:
                continue
            prv = utils.previous_sibling_tag(pre)

            # the first format: h3+pre
            if prv and prv.name == 'h3' and prv.string:
                yield (pre, prv)

            else:
                # ignore tags which are not samples
                # example: https://atcoder.jp/contests/abc003/tasks/abc003_4
                while prv is not None:
                    if prv.name == 'pre':
                        break
                    prv = utils.previous_sibling_tag(prv)
                if prv is not None:
                    continue

                # the second format: h3+section pre
                if pre.parent and pre.parent.name == 'section':
                    prv = pre.parent and utils.previous_sibling_tag(pre.parent)
                    if prv and prv.name == 'h3' and prv.string:
                        yield (pre, prv)

    def get_url(self) -> str:
        return 'http://{}.contest.atcoder.jp/tasks/{}'.format(self.contest_id, self.problem_id)

    def get_service(self) -> AtCoderService:
        return AtCoderService()

    def get_contest(self) -> AtCoderContest:
        return AtCoderContest(self.contest_id)

    @classmethod
    def from_url(cls, s: str) -> Optional['AtCoderProblem']:
        # example: http://agc012.contest.atcoder.jp/tasks/agc012_d
        result = urllib.parse.urlparse(s)
        dirname, basename = posixpath.split(utils.normpath(result.path))
        if result.scheme in ('', 'http', 'https') \
                and result.netloc.count('.') == 3 \
                and result.netloc.endswith('.contest.atcoder.jp') \
                and result.netloc.split('.')[0] \
                and dirname == '/tasks' \
                and basename:
            contest_id = result.netloc.split('.')[0]
            problem_id = basename
            return cls(contest_id, problem_id)

        # example: https://beta.atcoder.jp/contests/abc073/tasks/abc073_a
        m = re.match(r'^/contests/([\w\-_]+)/tasks/([\w\-_]+)$', utils.normpath(result.path))
        if result.scheme in ('', 'http', 'https') \
                and result.netloc in ('atcoder.jp', 'beta.atcoder.jp') \
                and m:
            contest_id = m.group(1)
            problem_id = m.group(2)
            return cls(contest_id, problem_id)

        return None

    def get_input_format(self, session: Optional[requests.Session] = None) -> str:
        session = session or utils.new_default_session()
        # get
        resp = _request('GET', self.get_url(), session=session)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        if AtCoderService._report_messages(msgs, unexpected=True):
            return ''
        # parse
        soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
        for h3 in soup.find_all('h3'):
            if h3.string in ('入力', 'Input'):
                tag = h3
                for _ in range(3):
                    tag = utils.next_sibling_tag(tag)
                    if tag is None:
                        break
                    if tag.name in ('pre', 'blockquote'):
                        s = ''
                        for it in tag:
                            s += it.string or it  # AtCoder uses <var>...</var> for math symbols
                        return s
        return ''

    def get_language_dict(self, session: Optional[requests.Session] = None) -> Dict[str, onlinejudge.type.Language]:
        session = session or utils.new_default_session()
        # get
        url = 'http://{}.contest.atcoder.jp/submit'.format(self.contest_id)
        resp = _request('GET', url, session=session)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        if AtCoderService._report_messages(msgs, unexpected=True):
            return {}
        # check whether logged in
        path = utils.normpath(urllib.parse.urlparse(resp.url).path)
        if path.startswith('/login'):
            log.error('not logged in')
            return {}
        # parse
        soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
        select = soup.find('select', class_='submit-language-selector')  # NOTE: AtCoder can vary languages depending on tasks, even in one contest. here, ignores this fact.
        language_dict = {}
        for option in select.find_all('option'):
            language_dict[option.attrs['value']] = {'description': option.string}
        return language_dict

    def submit_code(self, code: bytes, language: str, session: Optional[requests.Session] = None) -> onlinejudge.type.DummySubmission:
        assert language in self.get_language_dict(session=session)
        session = session or utils.new_default_session()
        # get
        url = 'http://{}.contest.atcoder.jp/submit'.format(self.contest_id)  # TODO: use beta.atcoder.jp
        resp = _request('GET', url, session=session)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        if AtCoderService._report_messages(msgs, unexpected=True):
            raise SubmissionError
        # check whether logged in
        path = utils.normpath(urllib.parse.urlparse(resp.url).path)
        if path.startswith('/login'):
            log.error('not logged in')
            raise SubmissionError
        # parse
        soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
        form = soup.find('form', action=re.compile(r'^/submit\?task_id='))
        if not form:
            log.error('form not found')
            raise SubmissionError
        log.debug('form: %s', str(form))
        # post
        task_id = self._get_task_id(session=session)
        form = utils.FormSender(form, url=resp.url)
        form.set('task_id', str(task_id))
        form.set('source_code', code)
        form.set('language_id_{}'.format(task_id), language)
        resp = form.request(session=session)
        resp.raise_for_status()
        # result
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        AtCoderService._report_messages(msgs)
        if '/submissions/me' in resp.url:
            # example: https://practice.contest.atcoder.jp/submissions/me#32174
            # CAUTION: this URL is not a URL of the submission
            log.success('success: result: %s', resp.url)
            # NOTE: ignore the returned legacy URL and use beta.atcoder.jp's one
            url = 'https://beta.atcoder.jp/contests/{}/submissions/me'.format(self.contest_id)
            return onlinejudge.type.DummySubmission(url)
        else:
            log.failure('failure')
            log.debug('redirected to %s', resp.url)
            raise SubmissionError

    def _get_task_id(self, session: Optional[requests.Session] = None) -> int:
        if self._task_id is None:
            session = session or utils.new_default_session()
            # get
            resp = _request('GET', self.get_url(), session=session)
            msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
            if AtCoderService._report_messages(msgs, unexpected=True):
                raise SubmissionError
            # parse
            soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
            submit = soup.find('a', href=re.compile(r'^/submit\?task_id='))
            if not submit:
                log.error('link to submit not found')
                raise SubmissionError
            m = re.match(r'^/submit\?task_id=([0-9]+)$', submit.attrs['href'])
            assert m
            self._task_id = int(m.group(1))
        return self._task_id

    def _load_details(self, session: Optional[requests.Session] = None) -> int:
        raise NotImplementedError

    def get_task_name(self) -> str:
        if self._task_name is None:
            self._load_details()
        assert self._task_name is not None
        return self._task_name

    def get_time_limit_msec(self) -> int:
        if self._time_limit_msec is None:
            self._load_details()
        assert self._time_limit_msec is not None
        return self._time_limit_msec

    def get_memory_limit_mb(self) -> int:
        if self._memory_limit_mb is None:
            self._load_details()
        assert self._memory_limit_mb is not None
        return self._memory_limit_mb

    def get_alphabet(self) -> str:
        if self._alphabet is None:
            self._load_details()
        assert self._alphabet is not None
        return self._alphabet


class AtCoderSubmission(onlinejudge.type.Submission):
    def __init__(self, contest_id: str, submission_id: int, problem_id: Optional[str] = None):
        self.contest_id = contest_id
        self.submission_id = submission_id
        self.problem_id = problem_id

    @classmethod
    def from_url(cls, s: str, problem_id: Optional[str] = None) -> Optional['AtCoderSubmission']:
        submission_id = None  # type: Optional[int]

        # example: http://agc001.contest.atcoder.jp/submissions/1246803
        result = urllib.parse.urlparse(s)
        dirname, basename = posixpath.split(utils.normpath(result.path))
        if result.scheme in ('', 'http', 'https') \
                and result.netloc.count('.') == 3 \
                and result.netloc.endswith('.contest.atcoder.jp') \
                and result.netloc.split('.')[0] \
                and dirname == '/submissions':
            contest_id = result.netloc.split('.')[0]
            try:
                submission_id = int(basename)
            except ValueError:
                pass
                submission_id = None
            if submission_id is not None:
                return cls(contest_id, submission_id, problem_id=problem_id)

        # example: https://beta.atcoder.jp/contests/abc073/submissions/1592381
        m = re.match(r'^/contests/([\w\-_]+)/submissions/(\d+)$', utils.normpath(result.path))
        if result.scheme in ('', 'http', 'https') \
                and result.netloc == ('atcoder.jp', 'beta.atcoder.jp') \
                and m:
            contest_id = m.group(1)
            try:
                submission_id = int(m.group(2))
            except ValueError:
                submission_id = None
            if submission_id is not None:
                return cls(contest_id, submission_id, problem_id=problem_id)

        return None

    def get_url(self) -> str:
        return 'http://{}.contest.atcoder.jp/submissions/{}'.format(self.contest_id, self.submission_id)

    def get_problem(self) -> AtCoderProblem:
        if self.problem_id is None:
            raise ValueError
        return AtCoderProblem(self.contest_id, self.problem_id)

    def get_service(self) -> AtCoderService:
        return AtCoderService()

    def download(self, session: Optional[requests.Session] = None) -> str:
        session = session or utils.new_default_session()
        # get
        resp = _request('GET', self.get_url(), session=session)
        msgs = AtCoderService._get_messages_from_cookie(resp.cookies)
        if AtCoderService._report_messages(msgs, unexpected=True):
            raise RuntimeError
        # parse
        soup = bs4.BeautifulSoup(resp.content.decode(resp.encoding), utils.html_parser)
        code = None
        for pre in soup.find_all('pre'):
            log.debug('pre tag: %s', str(pre))
            prv = utils.previous_sibling_tag(pre)
            if not (prv and prv.name == 'h3' and 'Source code' in prv.text):
                continue
            code = pre.string
        if code is None:
            log.error('source code not found')
            raise RuntimeError
        return code


onlinejudge.dispatch.services += [AtCoderService]
onlinejudge.dispatch.problems += [AtCoderProblem]
onlinejudge.dispatch.submissions += [AtCoderSubmission]
