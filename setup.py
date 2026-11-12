from setuptools import setup

with open('README.md', encoding='utf-8') as readme:
    README = readme.read()

setup(
    name='beets-userrating',
    author='djhibee (based on the work of Jean-Philippe Hautin)',
    description="A plugin for managing per-user track ratings in the music "
                "geek's media organizer",
    long_description=README,
    long_description_content_type='text/markdown',
    install_requires=[
        'beets >= 2.14.1', 'mutagen', 'mediafile',
        'beets-similarity @ https://github.com/djhibee/beets-similarity/'
        'archive/8dccafa8b7f8106d1be78276194bd0fda45d1412.zip',
    ],
    extras_require={'test': ['pytest']},
    python_requires='>=3.12',
    license='GPLv3',
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 3',
        'Topic :: Multimedia :: Sound/Audio',
    ],
    packages=['beetsplug', 'beetsplug.userrating'],
    platforms='ALL',
    url='https://github.com/djhibee/beets-userrating',
    version='1.0.0',
)
