import lintreview.github as github
import lintreview.git as git
import lintreview.tools as tools
import logging

from celery import Celery
from lintreview.config import load_config
from lintreview.config import ReviewConfig
from lintreview.diff import DiffCollection
from lintreview.review import Review
from lintreview.review import Problems

config = load_config()
celery = Celery('lintreview.tasks')
log = logging.getLogger(__name__)


@celery.task(ignore_result=True)
def process_pull_request(user, repo, number, lintrc):
    """
    Starts processing a pull request and running the various
    lint tools against it.
    """
    log.info('Starting to process lint for %s, %s, %s', user, repo, number)
    review_config = ReviewConfig(lintrc)

    gh = github.get_client(config, user, repo)
    try:
        log.debug('Loading pull request data from github.')
        pull_request = gh.pull_requests.get(number)
        head_repo = pull_request.head['repo']['git_url']
        pr_head = pull_request.head['sha']

        # Clone repository
        log.info("Cloning repository '%s' into '%s'",
                 head_repo, config['WORKSPACE'])
        target_path = git.get_repo_path(user, repo, number, config)
        if not git.exists(target_path):
            log.debug('Repo does not exist, cloning a new one.')
            git.clone(head_repo, target_path)

        # Check out new head
        log.info("Checking out '%s'", pr_head)
        git.checkout(target_path, pr_head)

        # Get changed files.
        log.debug('Loading pull request patches from github.')
        pull_request_patches = gh.pull_requests.list_files(number).all()
        changes = DiffCollection(pull_request_patches)

        problems = Problems(target_path)
        review = Review(gh, number)

        log.debug('Generating tool list from repository configuration')
        lint_tools = tools.factory(problems, review_config)

        files_to_check = changes.get_files(append_base=target_path)

        log.debug('Running lint tools on changed files.')
        for tool in lint_tools:
            tool.process_files(files_to_check)

        log.debug('Publishing review to github.')

        problems.limit_to(changes)
        review.publish(problems)

        log.info('Completed lint processing for %s, %s, %s' % (
            user, repo, number))
    except BaseException, e:
        log.exception(e)


@celery.task(ignore_result=True)
def cleanup_pull_request(user, repo, number):
    """
    Cleans up a pull request once its been closed.
    """
    log.info("Cleaning up pull request '%s' for %s/%s", number, user, repo)
    path = git.get_repo_path(user, repo, number, config)
    git.destroy(path)
