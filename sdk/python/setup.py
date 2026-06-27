from setuptools import setup, find_packages

setup(
    name="ai-team-hub",
    version="2.1.0",
    description=" Python SDK for AI Team Hub — Multi-Agent AI Runtime",
    long_description="One-line task execution: Client(api_key=\'...\').run(\'task\')",
    author="AI Team Hub",
    license="MIT",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.27.0",
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3",
    ],
)
