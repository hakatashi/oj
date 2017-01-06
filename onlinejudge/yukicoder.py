#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import onlinejudge
import onlinejudge.problem
import onlinejudge.implementation.utils as utils
from onlinejudge.logging import logger, prefix
import re
import io
import os.path
import bs4
import requests
import urllib.parse
import zipfile
import collections

class Yukicoder(onlinejudge.problem.OnlineJudge):
    service_name = 'yukicoder'

    def __init__(self, problem_no=None, problem_id=None):
        assert problem_no or problem_id
        assert not problem_no or isinstance(problem_no, int)
        assert not problem_id or isinstance(problem_id, int)
        self.problem_no = problem_no
        self.problem_id = problem_id

    def download(self, session=None, is_all=False):
        if is_all:
            return self.download_all(session=session)
        else:
            return self.download_samples(session=session)
    def download_samples(self, session=None):
        content = utils.download(self.get_url(), session)
        soup = bs4.BeautifulSoup(content, 'lxml')
        samples = utils.SampleZipper()
        for pre in soup.find_all('pre'):
            it = self.parse_sample_tag(pre)
            if it is not None:
                s, name = it
                samples.add(s, name)
        return samples.get()
    def download_all(self, session=None):
        url = 'http://yukicoder.me/problems/no/{}/testcase.zip'.format(self.problem_no)
        content = utils.download(url, session)
        samples = collections.defaultdict(list)
        with zipfile.ZipFile(io.BytesIO(content)) as fh:
            for name in sorted(fh.namelist()):  # "test_in" < "test_out"
                s = fh.read(name).decode()
                samples[os.path.basename(name)] += [( s, name )]
        return sorted(samples.values())

    def parse_sample_tag(self, tag):
        assert isinstance(tag, bs4.Tag)
        assert tag.name == 'pre'
        prv = tag.previous_sibling
        while prv and prv.string and prv.string.strip() == '':
            prv = prv.previous_sibling
        pprv = tag.parent.previous_sibling
        while pprv and pprv.string and pprv.string.strip() == '':
            pprv = pprv.previous_sibling
        if prv.name == 'h6' and tag.parent.name == 'div' and tag.parent['class'] == ['paragraph'] and pprv.name == 'h5':
            return tag.string.lstrip(), pprv.string + ' ' + prv.string

    def get_url(self):
        if self.problem_no:
            return 'https://yukicoder.me/problems/no/{}'.format(self.problem_no)
        elif self.problem_id:
            return 'https://yukicoder.me/problems/{}'.format(self.problem_id)
        else:
            assert False

    @classmethod
    def from_url(cls, s):
        m = re.match('^https?://yukicoder\.me/problems/(no/)?([0-9]+)/?$', s)
        if m:
            n = int(m.group(2).lstrip('0') or '0')
            if m.group(1):
                return cls(problem_no=int(n))
            else:
                return cls(problem_id=int(n))

    def login(self, get_credentials, session=None, method=None):
        if method == 'github':
            return self.login_with_github(session, get_credentials)
        elif method == 'twitter':
            return self.login_with_twitter(session, get_credentials)
        else:
            assert False
    def login_with_github(self, session, get_credentials):
        # get
        url = 'https://yukicoder.me/auth/github'
        logger.info(prefix['status'] + 'GET: %s', url)
        resp = session.get(url)
        logger.info(prefix['info'] + utils.describe_status_code(resp.status_code))
        resp.raise_for_status()
        if urllib.parse.urlparse(resp.url).hostname == 'yukicoder.me':
            logger.info(prefix['info'] + 'You have already signed in.')
            return True
        # redirect to github.com
        soup = bs4.BeautifulSoup(resp.content, 'lxml')
        form = soup.find('form')
        if not form:
            logger.error(prefix['error'] + 'form not found')
            logger.info(prefix['info'] + 'Did you logged in?')
            return False
        logger.debug(prefix['debug'] + 'form: %s', str(form))
        # post
        username, password = get_credentials()
        form = utils.FormSender(form, url=resp.url)
        form.set('login', username)
        form.set('password', password)
        resp = form.request(session)
        resp.raise_for_status()
        if urllib.parse.urlparse(resp.url).hostname == 'yukicoder.me':
            logger.info(prefix['success'] + 'You signed in.')
            return True
        else:
            logger.error(prefix['error'] + 'You failed to sign in. Wrong user ID or password.')
            return False

    def login_with_twitter(self, session, get_credentials):
        url = 'https://yukicoder.me/auth/twitter'
        raise NotImplementedError

    # Fri Jan  6 16:49:14 JST 2017
    _languages = []
    _languages += [( 'cpp', 'C++11 (gcc 4.8.5)' )]
    _languages += [( 'cpp14' , 'C++14 (gcc 6.2.0)' )]
    _languages += [( 'c', 'C (gcc 4.8.5)' )]
    _languages += [( 'java8', 'Java8 (openjdk 1.8.0_111)' )]
    _languages += [( 'csharp', 'C# (mono 4.6.1)' )]
    _languages += [( 'perl', 'Perl (5.16.3)' )]
    _languages += [( 'perl6', 'Perl6 (rakudo 2016.10-114-g8e79509)' )]
    _languages += [( 'php', 'PHP (5.4.16)' )]
    _languages += [( 'python', 'Python2 (2.7.11)' )]
    _languages += [( 'python3', 'Python3 (3.5.1)' )]
    _languages += [( 'pypy2', 'PyPy2 (4.0.0)' )]
    _languages += [( 'pypy3', 'PyPy3 (2.4.0)' )]
    _languages += [( 'ruby', 'Ruby (2.3.1p112)' )]
    _languages += [( 'd', 'D (dmd 2.071.1)' )]
    _languages += [( 'go', 'Go (1.7.3)' )]
    _languages += [( 'haskell', 'Haskell (7.8.3)' )]
    _languages += [( 'scala', 'Scala (2.11.8)' )]
    _languages += [( 'nim', 'Nim (0.15.2)' )]
    _languages += [( 'rust', 'Rust (1.12.1)' )]
    _languages += [( 'kotlin', 'Kotlin (1.0.2)' )]
    _languages += [( 'scheme', 'Scheme (Gauche-0.9.4)' )]
    _languages += [( 'crystal', 'Crystal (0.19.4)' )]
    _languages += [( 'ocaml', 'OCaml (4.01.1)' )]
    _languages += [( 'fsharp', 'F# (4.0)' )]
    _languages += [( 'elixir', 'Elixir (0.12.5)' )]
    _languages += [( 'lua', 'Lua (LuaJit 2.0.4)' )]
    _languages += [( 'fortran', 'Fortran (gFortran 4.8.5)' )]
    _languages += [( 'node', 'JavaScript (node v7.0.0)' )]
    _languages += [( 'vim', 'Vim script (v8.0.0124)' )]
    _languages += [( 'sh', 'Bash (Bash 4.2.46)' )]
    _languages += [( 'text', 'Text (cat 8.22)' )]
    _languages += [( 'nasm', 'Assembler (nasm 2.10.07)' )]
    _languages += [( 'bf', 'Brainfuck (BFI 1.1)' )]
    _languages += [( 'Whitespace', 'Whitespace (0.3)' )]
    def get_languages(self):
        return list(map(lambda l: l[0], self.__class__._languages))
    def get_language_description(self, s):
        return dict(self.__class__._languages)[s]

    def submit(self, code, language=None, session=None):
        assert language in self.get_languages()
        # get
        url = self.get_url() + '/submit'
        logger.info(prefix['status'] + 'GET: %s', url)
        resp = session.get(url)
        logger.info(prefix['info'] + utils.describe_status_code(resp.status_code))
        resp.raise_for_status()
        # post
        soup = bs4.BeautifulSoup(resp.content, 'lxml')
        form = soup.find('form', action=re.compile('/submit$'))
        if not form:
            logger.error(prefix['error'] + 'form not found')
            logger.info(prefix['info'] + 'Did you logged in?')
            return False
        form = utils.FormSender(form, url=resp.url)
        form.set('source', code)
        form.set('lang', language)
        resp = form.request(session=session)
        resp.raise_for_status()
        # result
        if re.match('^https?://yukicoder.me/submissions/[0-9]+/?$', resp.url):
            logger.info(prefix['success'] + 'success: result: %s', resp.url)
            return True
        else:
            logger.info(prefix['failure'] + 'failure')
            return False

onlinejudge.problem.list += [ Yukicoder ]