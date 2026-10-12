from setuptools import setup

setup(
    name='beets-userrating',
    author='djhibee (based on the work of Jean-Philippe Hautin)',
    description="A plugin for managing per-user track ratings in the music "
                "geek's media organizer",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    install_requires=['beets >= 2.0', 'mutagen', 'mediafile'],
    extras_require={'test': ['pytest']},
    python_requires='>=3.9',
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
