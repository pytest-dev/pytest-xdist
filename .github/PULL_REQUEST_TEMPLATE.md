Thanks for submitting a PR, your contribution is really appreciated!

Here's a quick checklist that should be present in PRs:

- [ ] Make sure to include reasonable tests for your change if necessary

- [ ] We use [towncrier](https://pypi.python.org/pypi/towncrier) for changelog management, so please add a *news* file into the `changelog` folder following these guidelines:
  * Name it `$issue_id.$type` for example `588.bugfix`;
  * If you don't have an issue_id change it to the PR id after creating it
  * Ensure type is one of `removal`, `feature`, `bugfix`, `vendor`, `doc` or `trivial`
  * Make sure to use full sentences with correct case and punctuation, for example:

    ```
    Fix issue with non-ascii contents in doctest text files.
    ```
