from __future__ import absolute_import
import os
import logging
import lintreview.docker as docker
from lintreview.tools import Tool, process_quickfix, stringify

log = logging.getLogger(__name__)


class Py3k(Tool):
    """
    $ pylint --py3k is a special mode for porting to python 3 which
    disables other pylint checkers.
    see https://github.com/PyCQA/pylint/issues/761
    """

    name = 'py3k'

    def check_dependencies(self):
        """
        See if python image is available
        """
        return docker.image_exists('python2')

    def match_file(self, filename):
        base = os.path.basename(filename)
        name, ext = os.path.splitext(base)
        return ext == '.py'

    def process_files(self, files):
        """
        Run code checks with pylint --py3k.
        Only a single process is made for all files
        to save resources.
        """
        log.debug('Processing %s files with %s', files, self.name)
        command = self.make_command(files)
        output = docker.run('python2', command, self.base_path)
        if not output:
            log.debug('No py3k errors found.')
            return False

        output = output.split("\n")
        output = [line for line in output if not line.startswith("*********")]

        process_quickfix(self.problems, output, docker.strip_base)

    def make_command(self, files):
        msg_template = '{path}:{line}:{column}:{msg_id} {msg}'
        command = [
            'pylint',
            '--py3k',
            '--reports=n',
            '--msg-template',
            msg_template,
        ]
        accepted_options = ('ignore')
        if 'ignore' in self.options:
            command.extend(['-d', stringify(self.options['ignore'])])
        if 'ignore-patterns' in self.options:
            command.extend([
                '--ignore-patterns',
                stringify(self.options['ignore-patterns'])
            ])

        for option in self.options:
            if option in accepted_options:
                continue
            log.warning('Set non-existent py3k option: %s', option)
        command.extend(files)
        return command
