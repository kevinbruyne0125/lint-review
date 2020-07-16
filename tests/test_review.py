import json
import responses
from unittest import TestCase

from . import load_fixture, fixer_ini
from lintreview.config import load_config, build_review_config
from lintreview.diff import DiffCollection, parse_diff
from lintreview.review import Review, Problems, Comment, IssueComment, InfoComment
from lintreview.repo import GithubRepository, GithubPullRequest
from github3.pulls import PullRequest as GhPullRequest
from github3.session import GitHubSession

config = load_config()


class TestReview(TestCase):

    def setUp(self):
        self.config = build_review_config(fixer_ini, config)

        self.session = GitHubSession()
        self.session.token_auth(config['GITHUB_OAUTH_TOKEN'])

    def create_repo(self):
        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test',
            json=json.loads(load_fixture('repository.json'))
        )
        return GithubRepository(config, 'markstory', 'lint-test')

    def create_pull(self):
        pull_request = GhPullRequest(json.loads(load_fixture('pull_request.json')), self.session)
        return GithubPullRequest(pull_request)

    def stub_labels(self):
        # Labels require several operations to ensure they exist.
        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/labels/No%20lint%20errors',
            json={},
            status=200)
        responses.add(
            responses.POST,
            'https://api.github.com/repos/markstory/lint-test/labels',
            json={},
            status=201)
        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/issues/1',
            json=json.loads(load_fixture('issue.json')),
            status=200)
        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/issues/1/labels?per_page=100',
            json=[
                {
                    "name": "No lint",
                    "color": "#ff0000",
                    "url": "https://api.github.com/repos/markstory/lint-test/labels/No%20lint"
                }
            ],
            status=200)

    def test_review_repr(self):
        comment = Comment('afile.txt', None, 40, "Some witty comment.")
        self.assertIn('Comment(filename=', str(comment))

    @responses.activate
    def test_load_comments__none_active(self):
        repo = self.create_repo()
        pull = self.create_pull()

        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/pulls/1/comments',
            json=json.loads(load_fixture('comments_none_current.json'))
        )
        review = Review(repo, pull, self.config)
        review.load_comments()

        filename = "View/Helper/AssetCompressHelper.php"
        self.assertEqual(0, len(review.comments(filename)))

    @responses.activate
    def test_load_comments__loads_comments(self):
        repo = self.create_repo()
        pull = self.create_pull()

        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/pulls/1/comments',
            json=json.loads(load_fixture('comments_current.json'))
        )
        review = Review(repo, pull, self.config)
        review.load_comments()

        filename = "Routing/Filter/AssetCompressor.php"
        res = review.comments(filename)
        self.assertEqual(1, len(res))
        expected = Comment(filename, None, 87, "A pithy remark")
        self.assertEqual(expected, res[0])

        filename = "View/Helper/AssetCompressHelper.php"
        res = review.comments(filename)
        self.assertEqual(2, len(res))
        expected = Comment(filename, None, 40, "Some witty comment.")
        self.assertEqual(expected, res[0])

        expected = Comment(filename, None, 89, "Not such a good comment")
        self.assertEqual(expected, res[1])

    @responses.activate
    def test_filter_existing__removes_duplicates(self):
        repo = self.create_repo()
        pull = self.create_pull()

        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/pulls/1/comments',
            json=json.loads(load_fixture('comments_current.json'))
        )
        problems = Problems()
        review = Review(repo, pull, self.config)
        filename_1 = "Routing/Filter/AssetCompressor.php"
        filename_2 = "View/Helper/AssetCompressHelper.php"

        problems.add(filename_1, 87, 'A pithy remark')
        problems.add(filename_1, 87, 'Something different')
        problems.add(filename_2, 88, 'I <3 it')
        problems.add(filename_2, 89, 'Not such a good comment')

        review.load_comments()
        review.remove_existing(problems)

        res = problems.all(filename_1)
        self.assertEqual(1, len(res))
        expected = Comment(filename_1,
                           87,
                           87,
                           'A pithy remark\nSomething different')
        self.assertEqual(res[0], expected)

        res = problems.all(filename_2)
        self.assertEqual(1, len(res))
        expected = Comment(filename_2, 88, 88, 'I <3 it')
        self.assertEqual(res[0], expected)

    @responses.activate
    def test_publish_pull_review(self):
        repo = self.create_repo()
        pull = self.create_pull()

        url = 'https://api.github.com/repos/markstory/lint-test/pulls/1/reviews'
        responses.add(responses.POST, url, json={})

        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            Comment(filename, 117, 117, 'Something bad'),
            Comment(filename, 119, 119, 'Something bad'),
        )
        problems = Problems()
        problems.add_many(errors)

        review = Review(repo, pull, self.config)
        review.publish_pull_review(problems, pull.head)

        responses.assert_call_count(url, 1)
        data = responses.calls[-1].request.body
        assert_review_data(data, errors, pull.head)

    @responses.activate
    def test_publish_pull_review__no_comments(self):
        repo = self.create_repo()
        pull = self.create_pull()

        problems = Problems()
        sha = 'abc123'

        review = Review(repo, pull, self.config)
        review.publish_pull_review(problems, sha)

        assert len(responses.calls) == 0

    @responses.activate
    def test_publish_pull_review__only_issue_comment(self):
        repo = self.create_repo()
        pull = self.create_pull()

        url = 'https://api.github.com/repos/markstory/lint-test/pulls/1/reviews'
        responses.add(responses.POST, url, json={})

        problems = Problems()
        problems.add(IssueComment('Very bad'))
        sha = 'abc123'

        review = Review(repo, pull, self.config)
        review.publish_pull_review(problems, sha)

        responses.assert_call_count(url, 1)
        data = responses.calls[0].request.body
        assert_review_data(data, [], sha, body='Very bad')

    @responses.activate
    def test_publish__join_issue_comments(self):
        repo = self.create_repo()
        pull = self.create_pull()
        problems = Problems()
        url = 'https://api.github.com/repos/markstory/lint-test/pulls/1/reviews'
        responses.add(responses.POST, url, json={})

        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            IssueComment('First'),
            Comment(filename, 119, 119, 'Something bad'),
            IssueComment('Second'),
        )
        problems.add_many(errors)
        sha = 'abc123'
        review = Review(repo, pull, self.config)
        review.publish_pull_review(problems, sha)

        responses.assert_call_count(url, 1)
        data = responses.calls[0].request.body
        assert_review_data(
            data,
            [errors[1]],
            sha,
            body='First\n\nSecond')

    @responses.activate
    def test_publish_status__ok_no_comment_or_label(self):
        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'OK_COMMENT': None,
            'OK_LABEL': None,
            'PULLREQUEST_STATUS': False,
        }

        repo = self.create_repo()
        pull = self.create_pull()
        review_config = build_review_config(fixer_ini, app_config)

        sha = pull.head
        url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + sha
        responses.add(responses.POST, url, json={}, status=201)

        review = Review(repo, pull, review_config)
        review.publish_status(False)

        responses.assert_call_count(url, 1)
        responses.assert_call_count('https://api.github.com/repos/markstory/lint-test', 1)
        assert len(responses.calls) == 2

    @responses.activate
    def test_publish_status__ok_with_comment_label(self):
        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'OK_COMMENT': 'Great job!',
            'OK_LABEL': 'No lint errors',
            'PULLREQUEST_STATUS': True,
        }

        repo = self.create_repo()
        pull = self.create_pull()
        review_config = build_review_config(fixer_ini, app_config)

        self.stub_labels()

        label_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/labels'
        responses.add(responses.POST, label_url, json={}, status=201)

        comment_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/comments'
        responses.add(responses.POST, comment_url, json={}, status=201)

        sha = pull.head
        status_url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + sha
        responses.add(responses.POST, status_url, json={}, status=201)

        review = Review(repo, pull, review_config)
        review.publish_status(False)

        responses.assert_call_count(label_url, 1)
        data = responses.calls[-3].request.body
        assert "No lint errors" == json.loads(data)[0]

        responses.assert_call_count(comment_url, 1)
        data = responses.calls[-2].request.body
        assert_comment(data, 'Great job!')

        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        assert_status(data, 'success', 'No lint errors found.')

    @responses.activate
    def test_publish_status__has_errors(self):
        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'OK_COMMENT': 'Great job!',
            'OK_LABEL': 'No lint errors',
            'APP_NAME': 'custom-name'
        }
        repo = self.create_repo()
        pull = self.create_pull()

        sha = pull.head
        status_url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + sha
        responses.add(responses.POST, status_url, json={}, status=201)

        review_config = build_review_config(fixer_ini, app_config)

        review = Review(repo, pull, review_config)
        review.publish_status(True)

        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        assert_status(data, 'failure', 'Lint errors found, see pull request comments.')

    @responses.activate
    def test_publish_status__has_errors__success_status(self):
        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'PULLREQUEST_STATUS': False,
            'OK_COMMENT': 'Great job!',
            'OK_LABEL': 'No lint errors',
            'APP_NAME': 'custom-name'
        }
        repo = self.create_repo()
        pull = self.create_pull()

        sha = pull.head
        status_url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + sha
        responses.add(responses.POST, status_url, json={}, status=201)

        review_config = build_review_config(fixer_ini, app_config)
        self.assertEqual('success', review_config.failed_review_status(),
                         'config object changed')

        review = Review(repo, pull, review_config)
        review.publish_status(True)

        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        assert_status(data, 'success', 'Lint errors found, see pull request comments.')

    @responses.activate
    def test_publish_pull_review_remove_ok_label(self):
        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            Comment(filename, 117, 117, 'Something bad'),
            Comment(filename, 119, 119, 'Something bad'),
        )
        problems = Problems()
        problems.add_many(errors)

        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'OK_LABEL': 'No lint',
        }
        review_config = build_review_config(fixer_ini, app_config)

        repo = self.create_repo()
        pull = self.create_pull()
        self.stub_labels()

        status_url = 'https://api.github.com/repos/markstory/lint-test/pulls/1/reviews'
        responses.add(responses.POST, status_url, json={}, status=200)

        label_remove_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/labels/No%20lint'
        responses.add(responses.DELETE, label_remove_url, json={}, status=200)

        review = Review(repo, pull, review_config)
        review.publish_pull_review(problems, pull.head)

        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        assert_review_data(data, errors, pull.head)

        responses.assert_call_count(label_remove_url, 1)

    @responses.activate
    def test_publish_review_empty_comment(self):
        repo = self.create_repo()
        pull = self.create_pull()

        status_url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + pull.head
        responses.add(responses.POST, status_url, json={}, status=201)

        comment_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/comments'
        responses.add(responses.POST, comment_url, json={}, status=201)

        problems = Problems(changes=DiffCollection([]))
        review = Review(repo, pull, self.config)

        review.publish_review(problems, pull.head)

        responses.assert_call_count(comment_url, 1)
        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        msg = ('Could not review pull request. '
               'It may be too large, or contain no reviewable changes.')
        assert_status(data, 'success', msg)

    @responses.activate
    def test_publish_review_empty_comment_remove_ok_label(self):
        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'OK_LABEL': 'No lint',
        }
        repo = self.create_repo()
        pull = self.create_pull()
        self.stub_labels()

        label_remove_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/labels/No%20lint'
        responses.add(responses.DELETE, label_remove_url, json={}, status=200)

        comment_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/comments'
        responses.add(responses.POST, comment_url, json={}, status=201)

        sha = pull.head
        status_url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + sha
        responses.add(responses.POST, status_url, json={}, status=201)

        problems = Problems(changes=DiffCollection([]))
        review_config = build_review_config(fixer_ini, app_config)
        review = Review(repo, pull, review_config)

        review.publish_review(problems, sha)

        responses.assert_call_count(comment_url, 1)
        msg = ('Could not review pull request. '
               'It may be too large, or contain no reviewable changes.')
        data = responses.calls[-3].request.body
        assert_comment(data, msg)

        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        assert_status(data, 'success', msg)

    @responses.activate
    def test_publish_review_comment_threshold_checks(self):
        repo = self.create_repo()
        pull = self.create_pull()
        app_config = {
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
            'SUMMARY_THRESHOLD': 1,
        }

        responses.add(
            responses.GET,
            'https://api.github.com/repos/markstory/lint-test/pulls/1/comments',
            json=json.loads(load_fixture('comments_current.json'))
        )
        sha = pull.head
        status_url = 'https://api.github.com/repos/markstory/lint-test/statuses/' + sha
        responses.add(responses.POST, status_url, json={}, status=200)

        comment_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/comments'
        responses.add(responses.POST, comment_url, json={}, status=201)

        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            Comment(filename, 117, 117, 'Something bad'),
            Comment(filename, 119, 119, 'Something bad'),
        )
        problems = Problems()
        problems.add_many(errors)
        problems.set_changes([1])

        review_config = build_review_config(fixer_ini, app_config)
        review = Review(repo, pull, review_config)
        review.publish_review(problems, sha)

        responses.assert_call_count(comment_url, 1)
        data = json.loads(responses.calls[-3].request.body)
        assert 'There are 2 errors:' in data['body']

        responses.assert_call_count(status_url, 1)
        data = responses.calls[-1].request.body
        assert_status(data, 'failure')

    @responses.activate
    def test_publish_summary(self):
        repo = self.create_repo()
        pull = self.create_pull()

        comment_url = 'https://api.github.com/repos/markstory/lint-test/issues/1/comments'
        responses.add(responses.POST, comment_url, json={}, status=201)

        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            IssueComment('Terrible things'),
            Comment(filename, 117, 117, 'Something bad'),
            Comment(filename, 119, 119, 'Something bad'),
        )
        problems = Problems()
        problems.add_many(errors)
        problems.set_changes([1])

        review_config = build_review_config(fixer_ini, config)
        review = Review(repo, pull, review_config)
        review.publish_summary(problems)

        responses.assert_call_count(comment_url, 1)

        msg = """There are 3 errors:

* Terrible things
* Console/Command/Task/AssetBuildTask.php, line 117 - Something bad
* Console/Command/Task/AssetBuildTask.php, line 119 - Something bad
"""
        data = responses.calls[-1].request.body
        assert_comment(data, msg)

    @responses.activate
    def test_publish_checkrun(self):
        app_config = {
            'PULLREQUEST_STATUS': True,
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
        }
        review_config = build_review_config(fixer_ini, app_config)

        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            Comment(filename, 117, 8, 'Something bad'),
            Comment(filename, 119, 9, 'Something worse'),
        )
        problems = Problems()
        problems.add_many(errors)

        repo = self.create_repo()
        pull = self.create_pull()

        run_id = 42
        run_url = 'https://api.github.com/repos/markstory/lint-test/check-runs/' + str(run_id)
        responses.add(responses.PATCH, run_url, json={}, status=200)

        review = Review(repo, pull, review_config)
        review.publish_checkrun(problems, run_id)

        responses.assert_call_count(run_url, 1)
        body = responses.calls[1].request.body
        assert_checkrun_data(body, problems)

    @responses.activate
    def test_publish_checkrun__multiple_chunks(self):
        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = [
            Comment(filename, i, i, 'Something worse')
            for i in range(0, 70)
        ]
        problems = Problems()
        problems.add_many(errors)
        problems.add(IssueComment('In the body'))

        run_id = 42
        run_url = 'https://api.github.com/repos/markstory/lint-test/check-runs/' + str(run_id)
        responses.add(responses.PATCH, run_url, json={}, status=200)

        repo = self.create_repo()
        pull = self.create_pull()
        app_config = {
            'PULLREQUEST_STATUS': True,
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
        }
        review_config = build_review_config(fixer_ini, app_config)
        review = Review(repo, pull, review_config)
        review.publish_checkrun(problems, run_id)

        responses.assert_call_count(run_url, 2)
        first_payload = json.loads(responses.calls[-2].request.body)

        assert 'failure' == first_payload['conclusion']

        assert 'completed_at' in first_payload
        assert 'title' in first_payload['output']
        assert 'summary' in first_payload['output']
        assert 'annotations' in first_payload['output']

        assert 'In the body' == first_payload['output']['summary']
        assert 50 == len(first_payload['output']['annotations'])

        # The second payload should only contain additional annotations.
        second_payload = json.loads(responses.calls[-1].request.body)
        assert 'completed_at' not in second_payload
        assert 'title' in second_payload['output']
        assert 'summary' in second_payload['output']
        assert 'annotations' in second_payload['output']
        assert 'In the body' == second_payload['output']['summary']
        assert 20 == len(second_payload['output']['annotations'])

    @responses.activate
    def test_publish_checkrun__has_errors_force_success_status(self):
        app_config = {
            'PULLREQUEST_STATUS': False,
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
        }
        review_config = build_review_config(fixer_ini, app_config)
        assert 'success' == review_config.failed_review_status(), 'config object changed'

        filename = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            Comment(filename, 117, 8, 'Something bad'),
            Comment(filename, 119, 9, 'Something worse'),
        )
        problems = Problems()
        problems.add_many(errors)

        run_id = 42
        run_url = 'https://api.github.com/repos/markstory/lint-test/check-runs/' + str(run_id)
        responses.add(responses.PATCH, run_url, json={}, status=200)

        repo = self.create_repo()
        pull = self.create_pull()
        review = Review(repo, pull, review_config)
        review.publish_checkrun(problems, run_id)

        responses.assert_call_count(run_url, 1)
        request_data = json.loads(responses.calls[-1].request.body)
        assert 'success' == request_data['conclusion']
        assert len(request_data['output']['annotations']) > 0

    @responses.activate
    def test_publish_checkrun__no_problems(self):
        app_config = {
            'PULLREQUEST_STATUS': True,
            'GITHUB_OAUTH_TOKEN': config['GITHUB_OAUTH_TOKEN'],
        }
        review_config = build_review_config(fixer_ini, app_config)

        run_id = 42
        run_url = 'https://api.github.com/repos/markstory/lint-test/check-runs/' + str(run_id)
        responses.add(responses.PATCH, run_url, json={}, status=200)

        problems = Problems()
        repo = self.create_repo()
        pull = self.create_pull()

        review = Review(repo, pull, review_config)
        review.publish_checkrun(problems, run_id)

        responses.assert_call_count(run_url, 1)
        body = responses.calls[-1].request.body
        assert_checkrun_data(body, problems)


class TestProblems(TestCase):
    two_files = load_fixture('diff/two_file_pull_request.txt')

    # Block offset so lines don't match offsets
    block_offset = load_fixture('diff/pull_request_line_offset.txt')

    def setUp(self):
        self.problems = Problems()

    def test_add(self):
        self.problems.add('file.py', 10, 'Not good')
        self.assertEqual(1, len(self.problems))

        self.problems.add('file.py', 11, 'Not good')
        self.assertEqual(2, len(self.problems))
        self.assertEqual(2, len(self.problems.all()))
        self.assertEqual(2, len(self.problems.all('file.py')))
        self.assertEqual(0, len(self.problems.all('not there')))

    def test_add__duplicate_is_ignored(self):
        self.problems.add('file.py', 10, 'Not good')
        self.assertEqual(1, len(self.problems))

        self.problems.add('file.py', 10, 'Not good')
        self.assertEqual(1, len(self.problems))

    def test_add__same_line_combines(self):
        self.problems.add('file.py', 10, 'Tabs bad')
        self.problems.add('file.py', 10, 'Spaces are good')
        self.assertEqual(1, len(self.problems))

        result = self.problems.all()
        expected = 'Tabs bad\nSpaces are good'
        self.assertEqual(expected, result[0].body)

    def test_add__same_line_ignores_duplicates(self):
        self.problems.add('file.py', 10, 'Tabs bad')
        self.problems.add('file.py', 10, 'Tabs bad')
        self.assertEqual(1, len(self.problems))

        result = self.problems.all()
        expected = 'Tabs bad'
        self.assertEqual(expected, result[0].body)

    def test_add__with_diff_containing_block_offset(self):
        changes = parse_diff(self.block_offset)

        problems = Problems(changes=changes)
        line_num = 32
        problems.add('somefile.py', line_num, 'Not good')
        self.assertEqual(1, len(problems))

        result = problems.all('somefile.py')
        first_result = result[0]
        self.assertIsInstance(first_result, Comment)
        self.assertEqual(
            changes.line_position('somefile.py', line_num),
            first_result.position,
            'Offset should be transformed to match value in changes'
        )

    def test_add_zero(self):
        self.problems.add('file.py', 0, 'Not good')
        result = self.problems.all('file.py')
        assert len(result) == 1, self.problems
        assert result[0].line == Comment.FIRST_LINE_IN_DIFF

    def test_add_many(self):
        errors = [
            Comment('some/file.py', 10, 10, 'Thing is wrong'),
            Comment('some/file.py', 12, 12, 'Not good'),
        ]
        self.problems.add_many(errors)
        result = self.problems.all('some/file.py')
        self.assertEqual(2, len(result))
        self.assertEqual(errors, result)

    def test_error_count(self):
        errors = [
            Comment('some/file.py', 10, 10, 'Thing is wrong'),
            Comment('some/file.py', 12, 12, 'Not good'),
        ]
        self.problems.add_many(errors)
        assert 2 == len(self.problems)
        assert 2 == self.problems.error_count()

    def test_error_count_exclude_info(self):
        errors = [
            Comment('some/file.py', 10, 10, 'Thing is wrong'),
            InfoComment('some content'),
        ]
        self.problems.add_many(errors)
        assert 1 == self.problems.error_count()
        assert 2 == len(self.problems)

    def test_limit_to_changes__remove_problems(self):
        changes = parse_diff(self.two_files)

        # Setup some fake problems.
        filename_1 = 'Console/Command/Task/AssetBuildTask.php'
        errors = (
            Comment(None, None, None, 'This is a general comment'),
            Comment(filename_1, 117, 117, 'Something bad'),
            Comment(filename_1, 119, 119, 'Something else bad'),
            Comment(filename_1, 130, 130, 'Filtered out, line is not changed'),
        )
        self.problems.add_many(errors)
        filename_2 = 'Test/test_files/View/Parse/single.ctp'
        errors = (
            Comment(filename_2, 2, 2, 'Filtered out'),
            Comment(filename_2, 3, 3, 'Something bad'),
            Comment(filename_2, 7, 7, 'Filtered out'),
        )
        self.problems.add_many(errors)
        self.problems.set_changes(changes)
        self.problems.limit_to_changes()

        result = self.problems.all(filename_1)
        self.assertEqual(2, len(result))
        expected = [
            Comment(filename_1, 117, 117, 'Something bad'),
            Comment(filename_1, 119, 119, 'Something else bad')]
        self.assertEqual(len(result), len(expected))
        self.assertEqual(result, expected)

        result = self.problems.all(filename_2)
        self.assertEqual(1, len(result))
        expected = [
            Comment(filename_2, 3, 3, 'Something bad')
        ]
        self.assertEqual(result, expected)

    def test_limit_to_changes__first_line_in_diff(self):
        changes = parse_diff(self.two_files)

        # Add problems
        filename = 'Test/test_files/View/Parse/single.ctp'
        errors = (
            Comment(filename, 5, 5, 'Something bad'),
            Comment(filename, Comment.FIRST_LINE_IN_DIFF, 0, 'First line!'),
            Comment(filename, 7, 7, 'Filtered out'),
        )
        self.problems.add_many(errors)
        self.problems.set_changes(changes)
        self.problems.limit_to_changes()

        result = self.problems.all(filename)
        self.assertEqual(2, len(result))
        expected = [
            Comment(filename, 5, 5, 'Something bad'),
            Comment(filename, 3, 3, 'First line!'),
        ]
        self.assertEqual(result, expected)

    def test_has_changes(self):
        problems = Problems(changes=None)
        self.assertFalse(problems.has_changes())

        problems = Problems(changes=[1])
        assert problems.has_changes()


def assert_label(request_data, label):
    data = json.loads(request_data)
    assert data['label'] == label


def assert_comment(request_data, comment):
    data = json.loads(request_data)
    assert data['body'] == comment


def assert_status(request_data, state, description=None):
    data = json.loads(request_data)
    assert data['state'] == state
    if description is not None:
        assert data['description'] == description


def assert_review_data(request_data, errors, sha, body=''):
    data = json.loads(request_data)
    comments = [error.payload() for error in errors]
    expected = {
        'commit_id': sha,
        'event': 'COMMENT',
        'body': body,
        'comments': comments
    }
    assert data.keys() == expected.keys()
    assert len(comments) == len(data['comments']), 'Error and comment counts are off.'


def assert_checkrun_data(request_data, errors):
    """
    Check that the review comments match the error list.
    """
    actual = json.loads(request_data)
    actual_annotations = actual['output']['annotations']
    expected = []
    for error in errors:
        value = {
            'message': error.body,
            'path': error.filename,
            'start_line': error.line,
            'end_line': error.line,
            'annotation_level': 'failure',
        }
        expected.append(value)

    assert len(expected) == len(actual_annotations)
    for i, item in enumerate(expected):
        assert item == actual_annotations[i]

    conclusion = 'success' if len(expected) == 0 else 'failure'
    assert conclusion == actual['conclusion'], 'conclusion bad'
    assert actual['completed_at'], 'required field completed_at missing'
    assert actual['output']['title'], 'required field output.title missing'
    assert 'summary' in actual['output'], 'required field output.summary missing'
