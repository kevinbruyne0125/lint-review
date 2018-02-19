from __future__ import absolute_import
import lintreview.docker as docker
from lintreview.review import Problems, Comment
from lintreview.tools.yamllint import Yamllint
from unittest import TestCase, skipIf
from nose.tools import eq_
from tests import root_dir

python_missing = not(docker.image_exists('python2'))


class TestYamllint(TestCase):

    needs_yamllint = skipIf(python_missing, 'Needs python2 image')

    fixtures = [
        'tests/fixtures/yamllint/no_errors.yaml',
        'tests/fixtures/yamllint/has_errors.yaml',
    ]

    def setUp(self):
        self.problems = Problems()
        self.tool = Yamllint(self.problems, {}, root_dir)

    def test_match_file(self):
        self.assertFalse(self.tool.match_file('test.php'))
        self.assertFalse(self.tool.match_file('test.js'))
        self.assertFalse(self.tool.match_file('dir/name/test.js'))
        self.assertTrue(self.tool.match_file('test.yaml'))
        self.assertTrue(self.tool.match_file('dir/name/test.yaml'))
        self.assertTrue(self.tool.match_file('test.yml'))
        self.assertTrue(self.tool.match_file('dir/name/test.yml'))

    @needs_yamllint
    def test_process_files__one_file_pass(self):
        self.tool.process_files([self.fixtures[0]])
        eq_([], self.problems.all(self.fixtures[0]))

    @needs_yamllint
    def test_process_files__one_file_fail(self):
        self.tool.process_files([self.fixtures[1]])
        problems = self.problems.all(self.fixtures[1])
        eq_(5, len(problems))

        fname = self.fixtures[1]

        msg = "[warning] missing starting space in comment (comments)"
        expected = Comment(fname, 1, 1, msg)
        eq_(expected, problems[0])

        msg = ("[warning] missing document start \"---\" (document-start)\n"
               "[error] too many spaces inside braces (braces)")
        expected = Comment(fname, 2, 2, msg)
        eq_(expected, problems[1])

    @needs_yamllint
    def test_process_files_two_files(self):
        self.tool.process_files(self.fixtures)

        eq_([], self.problems.all(self.fixtures[0]))

        problems = self.problems.all(self.fixtures[1])
        eq_(5, len(problems))

        fname = self.fixtures[1]

        msg = "[warning] missing starting space in comment (comments)"
        expected = Comment(fname, 1, 1, msg)
        eq_(expected, problems[0])

        msg = ("[warning] missing document start \"---\" (document-start)\n"
               "[error] too many spaces inside braces (braces)")
        expected = Comment(fname, 2, 2, msg)
        eq_(expected, problems[1])

    @needs_yamllint
    def test_process_files_with_config(self):
        config = {
            'config': 'tests/fixtures/yamllint/config.yaml'
        }
        tool = Yamllint(self.problems, config, root_dir)
        tool.process_files([self.fixtures[0]])

        problems = self.problems.all(self.fixtures[0])

        eq_(1, len(problems),
            'Config file should cause errors on no_errors.yml')
