from . import load_fixture
from contextlib import contextmanager
from lintreview.config import load_config
from lintreview.diff import DiffCollection
from lintreview.review import Review
from lintreview.review import Problems
from lintreview.review import Comment
from lintreview.review import IssueComment
from mock import patch
from mock import Mock
from mock import call
from nose.tools import eq_
from pygithub3 import Github
from pygithub3.resources.base import Resource
from requests.models import Response
from unittest import TestCase

config = load_config()


class TestReview(TestCase):

    def setUp(self):
        pr = Mock()
        issue = Mock()
        gh = Mock()

        gh.pull_request.return_value = pr
        gh.issue.return_value = issue

        self.gh, self.pr, self.issue = gh, pr, issue
        self.review = Review(self.gh, 2)

    def test_ensure_correct_pull_request_loaded(self):
        # Test the setup setup.
        self.gh.pull_request.assert_called_with(2)

    @patch('pygithub3.core.client.Client.get')
    def test_load_comments__none_active(self, http):
        fixture_data = load_fixture('comments_none_current.json')
        response = Response()
        response._content = fixture_data
        http.return_value = response

        gh = Github()
        review = Review(gh, 2)
        review.load_comments()

        eq_(0, len(review.comments("View/Helper/AssetCompressHelper.php")))

    @patch('pygithub3.core.client.Client.get')
    def test_load_comments__loads_comments(self, http):
        fixture_data = load_fixture('comments_current.json')
        response = Response()
        response._content = fixture_data
        http.return_value = response

        gh = Github()
        review = Review(gh, 2)
        review.load_comments()

        filename = "Routing/Filter/AssetCompressor.php"
        res = review.comments(filename)
        eq_(1, len(res))
        expected = Comment(filename, None, 87, "A pithy remark")
        eq_(expected, res[0])

        filename = "View/Helper/AssetCompressHelper.php"
        res = review.comments(filename)
        eq_(2, len(res))
        expected = Comment(filename, None, 40, "Some witty comment.")
        eq_(expected, res[0])

        expected = Comment(filename, None, 89, "Not such a good comment")
        eq_(expected, res[1])

    @patch('pygithub3.core.client.Client.get')
    def test_filter_existing__removes_duplicates(self, http):
        fixture_data = load_fixture('comments_current.json')
        response = Response()
        response._content = fixture_data
        http.return_value = response

        gh = Github()
        problems = Problems()
        review = Review(gh, 2)
        filename_1 = "Routing/Filter/AssetCompressor.php"
        filename_2 = "View/Helper/AssetCompressHelper.php"

        problems.add(filename_1, 87, 'A pithy remark')
        problems.add(filename_1, 87, 'Something different')
        problems.add(filename_2, 88, 'I <3 it')
        problems.add(filename_2, 89, 'Not such a good comment')

        review.load_comments()
        review.remove_existing(problems)

        res = problems.all(filename_1)
        eq_(1, len(res))
        expected = Comment(filename_1, 87, 87, 'Something different')
        eq_(res[0], expected)

        res = problems.all(filename_2)
        eq_(1, len(res))
        expected = Comment(filename_2, 88, 88, 'I <3 it')
        eq_(res[0], expected)

    def test_publish_problems(self):
        gh = Mock()
        problems = Problems()

        filename_1 = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            (filename_1, 117, 'Something bad'),
            (filename_1, 119, 'Something bad'),
        )
        problems.add_many(errors)
        sha = 'abc123'

        review = Review(gh, 3)
        review.publish_problems(problems, sha)

        assert gh.pull_requests.comments.create.called
        eq_(2, gh.pull_requests.comments.create.call_count)
        calls = gh.pull_requests.comments.create.call_args_list

        expected = call(3, {
            'commit_id': sha,
            'path': errors[0][0],
            'position': errors[0][1],
            'body': errors[0][2]
        })
        eq_(calls[0], expected)

        expected = call(3, {
            'commit_id': sha,
            'path': errors[1][0],
            'position': errors[1][1],
            'body': errors[1][2]
        })
        eq_(calls[1], expected)

    def test_publish_problems_add_ok_label(self):
        problems = Problems()

        filename_1 = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            (filename_1, 117, 'Something bad'),
            (filename_1, 119, 'Something bad'),
        )
        problems.add_many(errors)
        sha = 'abc123'

        review = Review(self.gh, 3)
        label = config.get('OK_LABEL', 'No lint errors')

        label_obj = Mock()
        label_obj.name = label
        self.issue.labels.return_value = (label_obj,)

        with add_ok_label(self.gh, 3, label):
            sha = 'abc123'
            review.publish_problems(problems, sha)

        assert self.issue.remove_label.called
        assert self.pr.create_review_comment.called
        eq_(2, self.pr.create_review_comment.call_count)
        assert_add_to_issue(self.gh)

        calls = self.issue.remove_label.call_args_list

        expected = call(label)
        eq_(calls, [expected])

        calls = self.pr.create_review_comment.call_args_list

        expected = call(
            commit_id=sha,
            path=errors[0][0],
            position=errors[0][1],
            body=errors[0][2]
        )
        eq_(calls[0], expected)

        expected = call(
            commit_id=sha,
            path=errors[1][0],
            position=errors[1][1],
            body=errors[1][2]
        )
        eq_(calls[1], expected)

    def test_publish_ok_comment(self):
        gh = Mock()
        problems = Problems(changes=[1])
        review = Review(gh, 3)

        sha = 'abc123'
        review.publish(problems, sha)

        assert not(gh.pull_requests.comments.create.called)
        assert gh.issues.comments.create.called

        calls = gh.issues.comments.create.call_args_list

        expected = call(
            3, config.get('OK_COMMENT', ':+1: No lint errors found.'))
        eq_(calls[0], expected)

    def test_publish_ok_comment_add_ok_label(self):
        gh = Mock()
        problems = Problems(changes=[1])
        review = Review(gh, 3)
        label = config.get('OK_LABEL', 'No lint errors')

        with add_ok_label(gh, 3, label, create=True):
            sha = 'abc123'
            review.publish(problems, sha)

        assert not gh.pull_requests.comments.create.called
        assert not gh.issues.comments.create.called
        assert gh.issues.labels.remove_from_issue.called

        calls = gh.issues.labels.remove_from_issue.call_args_list

        expected = call(3, label)
        eq_(calls, [expected])

        assert_add_to_issue(gh, 3, label, create=True)
        assert not(gh.pull_requests.comments.create.called)

    def test_publish_empty_comment(self):
        problems = Problems(changes=[])
        review = Review(self.gh, 3)

        sha = 'abc123'
        review.publish(problems, sha)

        assert self.issue.create_comment.called

        calls = self.issue.create_comment.call_args_list

        msg = ('Could not review pull request. '
               'It may be too large, or contain no reviewable changes.')
        expected = call(msg)
        eq_(calls[0], expected)

    def test_publish_empty_comment_add_ok_label(self):
        problems = Problems(changes=[])
        review = Review(self.gh, 3)
        label = config.get('OK_LABEL', 'No lint errors')

        with add_ok_label(self.gh, 3, label):
            sha = 'abc123'
            review.publish(problems, sha)

        assert self.pr.create_comment.called
        assert gh.issues.labels.remove_from_issue.called
        assert_add_to_issue(gh)

        calls = gh.issues.labels.remove_from_issue.call_args_list

        expected = call(3, label)
        eq_(calls, [expected])

        calls = gh.issues.comments.create.call_args_list

        msg = ('Could not review pull request. '
               'It may be too large, or contain no reviewable changes.')
        expected = call(3, msg)
        eq_(calls[0], expected)

    @patch('pygithub3.core.client.Client.get')
    def test_publish_comment_threshold_checks(self, http):
        fixture_data = load_fixture('comments_current.json')
        response = Response()
        response._content = fixture_data
        http.return_value = response

        gh = Github()
        problems = Problems()

        filename_1 = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            (filename_1, 117, 'Something bad'),
            (filename_1, 119, 'Something bad'),
        )
        problems.add_many(errors)
        problems.set_changes([1])
        sha = 'abc123'

        review = Review(gh, 3)
        review.publish_summary = Mock()
        review.publish(problems, sha, 1)

        assert review.publish_summary.called, 'Should have been called.'

    def test_publish_summary(self):
        problems = Problems()

        filename_1 = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            (filename_1, 117, 'Something bad'),
            (filename_1, 119, 'Something bad'),
        )
        problems.add_many(errors)
        problems.set_changes([1])
        sha = 'abc123'

        review = Review(self.gh, 3)
        review.publish_summary(problems)

        assert self.issue.create_comment.called
        eq_(1, self.issue.create_comment.call_count)
        calls = self.issue.create_comment.call_args_list

        msg = """There are 2 errors:

* Console/Command/Task/AssetBuildTask.php, line 117 - Something bad
* Console/Command/Task/AssetBuildTask.php, line 119 - Something bad
"""
        expected = call(msg)
        eq_(calls[0], expected)


class TestProblems(TestCase):

    two_files_json = load_fixture('two_file_pull_request.json')

    # Block offset so lines don't match offsets
    block_offset = load_fixture('pull_request_line_offset.json')

    def setUp(self):
        self.problems = Problems()

    def test_add(self):
        self.problems.add('file.py', 10, 'Not good')
        eq_(1, len(self.problems))

        self.problems.add('file.py', 11, 'Not good')
        eq_(2, len(self.problems))
        eq_(2, len(self.problems.all()))
        eq_(2, len(self.problems.all('file.py')))
        eq_(0, len(self.problems.all('not there')))

    def test_add__duplicate_is_ignored(self):
        self.problems.add('file.py', 10, 'Not good')
        eq_(1, len(self.problems))

        self.problems.add('file.py', 10, 'Not good')
        eq_(1, len(self.problems))

    def test_add__with_base_path(self):
        problems = Problems('/some/path/')
        problems.add('/some/path/file.py', 10, 'Not good')
        eq_([], problems.all('/some/path/file.py'))
        eq_(1, len(problems.all('file.py')))
        eq_(1, len(problems))

    def test_add__with_base_path_no_trailing_slash(self):
        problems = Problems('/some/path')
        problems.add('/some/path/file.py', 10, 'Not good')
        eq_([], problems.all('/some/path/file.py'))
        eq_(1, len(problems.all('file.py')))
        eq_(1, len(problems))

    def test_add__with_diff_containing_block_offset(self):
        res = Resource.loads(self.block_offset)
        changes = DiffCollection(res)

        problems = Problems(changes=changes)
        line_num = 32
        problems.add('somefile.py', line_num, 'Not good')
        eq_(1, len(problems))

        result = problems.all('somefile.py')
        eq_(changes.line_position('somefile.py', line_num), result[0].position,
            'Offset should be transformed to match value in changes')

    def test_add_many(self):
        errors = [
            ('some/file.py', 10, 'Thing is wrong'),
            ('some/file.py', 12, 'Not good'),
        ]
        self.problems.add_many(errors)
        result = self.problems.all('some/file.py')
        eq_(2, len(result))
        expected = [
            Comment(errors[0][0], errors[0][1], errors[0][1], errors[0][2]),
            Comment(errors[1][0], errors[1][1], errors[1][1], errors[1][2]),
        ]
        eq_(expected, result)

    def test_limit_to_changes__remove_problems(self):
        res = Resource.loads(self.two_files_json)
        changes = DiffCollection(res)

        # Setup some fake problems.
        filename_1 = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            (None, None, 'This is a general comment'),
            (filename_1, 117, 'Something bad'),
            (filename_1, 119, 'Something else bad'),
            (filename_1, 130, 'Filtered out, as line is not changed'),
        )
        self.problems.add_many(errors)
        filename_2 = 'Test/test_files/View/Parse/single.ctp'
        errors = (
            (filename_2, 2, 'Filtered out'),
            (filename_2, 3, 'Something bad'),
            (filename_2, 7, 'Filtered out'),
        )
        self.problems.add_many(errors)
        self.problems.set_changes(changes)
        self.problems.limit_to_changes()

        result = self.problems.all(filename_1)
        eq_(2, len(result))
        expected = [
            (None, None, 'This is a general comment'),
            (filename_1, 117, 'Something bad'),
            (filename_1, 119, 'Something else bad')]
        eq_(result.sort(), expected.sort())

        result = self.problems.all(filename_2)
        eq_(1, len(result))
        expected = [
            Comment(filename_2, 3, 3, 'Something bad')
        ]
        eq_(result, expected)

    def test_has_changes(self):
        problems = Problems(changes=None)
        self.assertFalse(problems.has_changes())

        problems = Problems(changes=[1])
        assert problems.has_changes()


@contextmanager
def add_ok_label(gh, pr_number, *labels, **kw):
    from lintreview.review import config
    from pygithub3.exceptions import NotFound

    if labels:
        class Label(object):
            def __init__(self, name):
                self.name = name
        gh.issues.labels.list_by_issue.return_value = [Label(n) for n in labels]

        if kw.get("create"):
            gh.issues.labels.get.side_effect = NotFound

    eq_(config["ADD_OK_LABEL"], False)
    config["ADD_OK_LABEL"] = True
    try:
        yield
    finally:
        config["ADD_OK_LABEL"] = False


def assert_add_to_issue(gh, *pr_number_and_labels, **kw):
    if not pr_number_and_labels:
        assert not gh.issues.labels.add_to_issue.called
    else:
        import json
        pr_number = pr_number_and_labels[0]
        labels = list(pr_number_and_labels[1:])

        if kw.get("create"):
            expected = call({
                "name": labels[0],
                "color": "bfe5bf",
            })
            eq_(gh.issues.labels.create.call_args_list, [expected])

        # the assertion should be this simple, but bugs...
        #expected = call(pr_number, labels)
        #eq_(gh.issues.labels.add_to_issue.call_args_list, [expected])

        assert gh.issues.labels.make_request.called
        expected = call(
            'issues.labels.add_to_issue',
            user=None,
            repo=None,
            number=pr_number,
            body=json.dumps(labels)
        )
        eq_(gh.issues.labels.make_request.call_args_list, [expected])
        eq_(gh.issues.labels._client.request.call_count, 1)
