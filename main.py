from __future__ import annotations

import collections
import pathlib
import argparse
import re
from importlib.metadata import PackageNotFoundError, version, requires, distributions
from typing import List, Generator, Tuple, Set, Mapping

def helper_packages_distributions() -> Mapping[str, List[str]]:
    """
    Copied from importlib.metadata for Python3.8 support
    """
    pkg_to_dist = collections.defaultdict(list)
    for dist in distributions():
        for pkg in (dist.read_text('top_level.txt') or '').split():
            pkg_to_dist[pkg].append(dist.metadata['Name'])
    return dict(pkg_to_dist)

class DistributionDB:
    _regex_requirement_split = re.compile(r"([^;]+)")
    _regex_version = re.compile(r"([^\(]+)(\(([^\)]+))*")

    class DistributionEntry:
        def __init__(self, provided_dist_name: str, version_str: str = None) -> None:
            self.__name = provided_dist_name
            self.__currently_processed = True
            self.__version_provided = True if version_str is not None else False
            self.__version_detected = False
            self.__requirements: Set[DistributionDB.DistributionEntry] = set()

            if version_str is None:
                try:
                    self.__version = version(self.__name)
                    self.__version_detected = True
                except PackageNotFoundError:
                    try:
                        self.__version = getattr(__import__(self.__name), "__version__")
                        self.__version_detected = True
                    except (ModuleNotFoundError, AttributeError):
                        self.__version = ""
            else:
                self.__version = version_str

        def inspect_requirements(self) -> Generator[Tuple[str, str], None, None]:
            installed = True
            dist_requirements = None
            try:
                dist_requirements = requires(self.__name)
            except PackageNotFoundError:
                installed = False
            if installed:
                if dist_requirements is not None:
                    for dist_requirement in dist_requirements:
                        concrete_requirement = DistributionDB._regex_requirement_split.match(dist_requirement)
                        if concrete_requirement:
                            concrete_requirement_str = concrete_requirement[0].strip()
                            result = DistributionDB._regex_version.search(concrete_requirement_str)
                            yield result.group(1), result.group(3)

        def requirements(self) -> Generator[DistributionDB.DistributionEntry, None, None]:
            for current_requirement in self.__requirements:
                yield current_requirement

        def add_requirement(self, entry: DistributionDB.DistributionEntry) -> None:
            self.__requirements.add(entry)

        def finalize(self) -> None:
            self.__currently_processed = False

        @property
        def finalized(self) -> bool:
            return not self.__currently_processed

        @property
        def name(self) -> str:
            return self.__name

        @property
        def version(self) -> str:
            return self.__version

        def __eq__(self, other):
            if isinstance(other, self.__class__):
                return self.name.lower() == other.name.lower() and self.version == other.version

        def __gt__(self, other):
            if isinstance(other, self.__class__):
                if self.name.lower() > other.name.lower():
                    return True
                if self.name.lower() == other.name.lower():
                    return self.version > other.version
                return False

        def __ne__(self, other):
            return not self == other

        def __ge__(self, other):
            return self == other or self > other

        def __lt__(self, other):
            return not self >= other

        def __le__(self, other):
            return not self < other

        def __hash__(self):
            return hash((self.name, self.version))

        def __str__(self):
            if self.__version_provided:
                return f"{self.name}{self.version}"
            else:
                if self.__version_detected:
                    return f"{self.name} ={self.version}"
                else:
                    return f"{self.name}"

    def __done(self) -> bool:
        for current_distribution_entry in self.__known_distributions:
            if not current_distribution_entry.finalized:
                return False
        return True

    def find(self, provided_distribution_name: str, provided_version: str):
        h = hash((provided_distribution_name, provided_version))
        for d in self.__known_distributions:
            if hash(d) == h:
                return d
        return None

    def find_by_name(self, provided_distribution_name: str) -> List[DistributionDB.DistributionEntry]:
        result = []
        for d in self.__known_distributions:
            if d.name == provided_distribution_name:
                result.append(d)
        return result

    def package_known(self, package_name: str):
        return package_name in self.__installed_packages

    def find_from_package(self, package_name: str) -> List[str]:
        if package_name in self.__installed_packages:
            return self.__installed_packages[package_name]

    def __init__(self):
        self.__known_distributions: Set[DistributionDB.DistributionEntry] = set()
        self.__installed_packages: Mapping[str, List[str]] = helper_packages_distributions()
        for distribution_names in self.__installed_packages.values():
            for current_distribution_name in distribution_names:
                distribution_obj = DistributionDB.DistributionEntry(current_distribution_name)
                if distribution_obj not in self.__known_distributions:
                    self.__known_distributions.add(distribution_obj)

        while not self.__done():
            requirements_to_add: Set[DistributionDB.DistributionEntry] = set()
            for current_distribution_entry in self.__known_distributions:
                if not current_distribution_entry.finalized:
                    for requirement_tuple in current_distribution_entry.inspect_requirements():
                        requirement_object = self.find(requirement_tuple[0], requirement_tuple[1])
                        if requirement_object is None:
                            requirement_object = DistributionDB.DistributionEntry(requirement_tuple[0],
                                                                                  requirement_tuple[1])
                        current_distribution_entry.add_requirement(requirement_object)
                        requirements_to_add.add(requirement_object)
                    current_distribution_entry.finalize()
            self.__known_distributions.update(requirements_to_add)

    def print(self):
        for dist in self.__known_distributions:
            print(f"{dist}")


def get_imports_from_root(root_path: pathlib.Path) -> List[str]:
    files = [f for f in root_path.rglob("*.py") if 'venv' not in f"{f}"]
    regex_import = re.compile(r"(import (\S+)\s*)|(from\s+(\S+)\s+import\s+\S+)")
    regex_split = re.compile(r"([^.,\s]+)")

    current_imports = set()
    for f in files:
        with open(f, 'r') as py:
            lines = py.read()
            matches = regex_import.finditer(lines, re.MULTILINE)
            for matchNum, match in enumerate(matches, start=1):
                import_match = match.group(2) if match.group(2) is not None else match.group(4)
                to_add_match = regex_split.match(import_match)
                if to_add_match:
                    current_imports.add(to_add_match[0])
    imports_list = list(current_imports)
    imports_list.sort()
    return imports_list


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--tvlRootPath', type=pathlib.Path, dest="rootPath")
    parser.add_argument('-o', '--out', type=pathlib.Path, dest="outPath",
                        default=pathlib.Path("./out/requirements.txt"))
    args = parser.parse_args()

    args_dict = {key: value for key, value in vars(args).items()}

    out = pathlib.Path(args_dict["outPath"]).resolve()
    if len(out.suffixes) == 0:
        out.mkdir(exist_ok=True)
        out.joinpath("requirements.txt")
    else:
        out.parent.mkdir(exist_ok=True)

    rootPath = pathlib.Path(args_dict["rootPath"])

    imports = get_imports_from_root(rootPath)
    distro_db = DistributionDB()

    distribution_list: List[str] = []
    output_list: List[DistributionDB.DistributionEntry] = []

    with open(out, "w") as file:
        file.write("# ========= BEGIN Dependencies of required packages ========= #\n")
        for import_package_name in imports:
            if distro_db.package_known(import_package_name):
                for distribution_name in distro_db.find_from_package(import_package_name):
                    for distribution_entry in distro_db.find_by_name(distribution_name):
                        file.write(f"# Requirement for {distribution_entry}\n")
                        for requirement in distribution_entry.requirements():
                            if str(requirement) not in distribution_list:
                                file.write(f"# \t{str(requirement)}\n")
                                distribution_list.append(str(requirement))
                                output_list.append(requirement)
        output_list.sort()
        for r in output_list:
            file.write(f"{r}\n")
        output_list.clear()
        file.write("# =========  END  Dependencies of required packages ========= #\n")

        file.write("# ========= BEGIN         Required packages         ========= #\n")
        for import_package_name in imports:
            if distro_db.package_known(import_package_name):
                for distribution_name in distro_db.find_from_package(import_package_name):
                    for distribution_entry in distro_db.find_by_name(distribution_name):
                        if str(distribution_entry) not in distribution_list:
                            distribution_list.append(str(distribution_entry))
                            output_list.append(distribution_entry)
        output_list.sort()
        for r in output_list:
            file.write(f"{r}\n")
        file.write("# =========  END          Required packages         ========= #\n")
        for import_package_name in imports:
            if not distro_db.package_known(import_package_name):
                file.write(f"# Doesn't know package {import_package_name}.\n")

