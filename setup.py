from setuptools import setup, find_packages

setup(
    name="smtp-stress-test",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "fastapi",
        "uvicorn",
        "aiofiles",
        "pandas",
        "jinja2",
        "aiosmtplib"
    ]
)
