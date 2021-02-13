import re
import fnmatch
import os
import py  # TODO remove
import pytest


def parse_spec_config(config):
    xspeclist = []
    for xspec in config.getvalue("tx"):
        i = xspec.find("*")
        try:
            num = int(xspec[:i])
        except ValueError:
            xspeclist.append(xspec)
        else:
            xspeclist.extend([xspec[i + 1 :]] * num)
    if not xspeclist:
        raise pytest.UsageError(
            "MISSING test execution (tx) nodes: please specify --tx"
        )
    return xspeclist


class ExecnetNodeControl:
    @classmethod
    def from_config(cls, config, specs, defaultchdir):
        final_specs = []

        import execnet

        group = execnet.Group()
        if specs is None:
            specs = [execnet.XSpec(x) for x in parse_spec_config(config)]
        for spec in specs:
            if not isinstance(spec, execnet.XSpec):
                spec = execnet.XSpec(spec)
            if not spec.chdir and not spec.popen:
                spec.chdir = defaultchdir
            group.allocate_id(spec)
            final_specs.append(spec)

        return cls(group, final_specs)

    def __init__(self, group, specs):
        self.group = group
        self.specs = specs

    @staticmethod
    def get_rsync(source, verbose=False, ignores=None):
        import execnet

        # todo: cache the class
        class HostRSync(execnet.RSync):
            """ RSyncer that filters out common files
            """

            def __init__(self, sourcedir, *args, **kwargs):
                self._synced = {}
                ignores = kwargs.pop("ignores", None) or []
                self._ignores = [
                    re.compile(fnmatch.translate(getattr(x, "strpath", x)))
                    for x in ignores
                ]
                super().__init__(sourcedir=sourcedir, **kwargs)

            def filter(self, path):
                path = py.path.local(path)
                for cre in self._ignores:
                    if cre.match(path.basename) or cre.match(path.strpath):
                        return False
                else:
                    return True

            def add_target_host(self, gateway, finished=None):
                remotepath = os.path.basename(self._sourcedir)
                super().add_target(
                    gateway, remotepath, finishedcallback=finished, delete=True
                )

            def _report_send_file(self, gateway, modified_rel_path):
                if self._verbose > 0:
                    path = os.path.basename(self._sourcedir) + "/" + modified_rel_path
                    remotepath = gateway.spec.chdir
                    print("{}:{} <= {}".format(gateway.spec, remotepath, path))

        return HostRSync(source, verbose=verbose, ignores=ignores)
