#!/usr/bin/env python
from setuptools import setup, find_packages

PACKAGE_NAME = "Lint Review"
VERSION = "0.0.1"

requirements = open('./requirements.txt', 'r')

setup(
    name=PACKAGE_NAME,
    version=VERSION,
    description="""
    Lint Review, an automated code review tool that integrates with github.
    Integrates with the github API & a variety of code checking tools.
    """,
    author="Mark story",
    author_email="mark@mark-story.com",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'register_hooks = scripts.register_hooks:main',
            'runserver = scripts.runserver:main',
        ],
    },
    install_requires=requirements.readlines(),
)
