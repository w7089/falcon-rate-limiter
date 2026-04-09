"""Release helpers for version bumps and Git tags.

This script keeps release automation explicit: `pyproject.toml` remains the
single source of truth for the package version, while Git tags use the matching
`vX.Y.Z` format required by the publish workflow.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import tomllib

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PYPROJECT_VERSION_PATTERN = re.compile(
    r'(?m)^(version\s*=\s*")(?P<version>\d+\.\d+\.\d+)(")$'
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for release operations.

    Returns:
        The parsed command namespace including the selected subcommand.
    """

    parser = argparse.ArgumentParser(
        description="Manage package versions and release tags."
    )
    parser.add_argument(
        "--pyproject",
        type=pathlib.Path,
        default=pathlib.Path("pyproject.toml"),
        help="Path to the pyproject.toml file to read or update.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "current-version",
        help="Print the current package version from pyproject.toml.",
    )

    bump_parser = subparsers.add_parser(
        "bump",
        help="Bump the package version using semantic versioning.",
    )
    bump_parser.add_argument(
        "part",
        nargs="?",
        choices=("patch", "minor", "major"),
        default="patch",
        help="Version component to bump. Defaults to patch.",
    )

    tag_parser = subparsers.add_parser(
        "release-tag",
        help="Create a Git tag that matches the current package version.",
    )
    tag_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the tag that would be created without creating it.",
    )

    return parser.parse_args()


def read_version(pyproject_path: pathlib.Path) -> str:
    """Read the project version from a `pyproject.toml` file.

    Args:
        pyproject_path: The `pyproject.toml` file containing project metadata.

    Returns:
        The package version stored in `[project].version`.

    Raises:
        FileNotFoundError: If the target file does not exist.
        KeyError: If the file does not define `[project].version`.
        tomllib.TOMLDecodeError: If the file content is not valid TOML.
        ValueError: If the version is not a valid `MAJOR.MINOR.PATCH` string.
    """

    data = tomllib.loads(pyproject_path.read_text())
    version = data["project"]["version"]
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"Unsupported version format: {version!r}")
    return version


def bump_version(version: str, part: str) -> str:
    """Return the next semantic version for the requested release type.

    Args:
        version: The current semantic version string.
        part: The version component to increment: `patch`, `minor`, or `major`.

    Returns:
        The incremented semantic version string.

    Raises:
        ValueError: If `version` is not semantic versioned or `part` is unknown.
    """

    match = SEMVER_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"Unsupported version format: {version!r}")

    major, minor, patch = (int(component) for component in match.groups())

    if part == "patch":
        patch += 1
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unsupported release part: {part!r}")

    return f"{major}.{minor}.{patch}"


def write_version(pyproject_path: pathlib.Path, new_version: str) -> None:
    """Persist an updated project version back to `pyproject.toml`.

    Args:
        pyproject_path: The `pyproject.toml` file to update.
        new_version: The semantic version string that should replace the current one.

    Returns:
        None.

    Raises:
        ValueError: If the file does not contain a replaceable `project.version`
            entry or if `new_version` is not semantic versioned.
    """

    if SEMVER_PATTERN.fullmatch(new_version) is None:
        raise ValueError(f"Unsupported version format: {new_version!r}")

    contents = pyproject_path.read_text()
    updated_contents, replacements = PYPROJECT_VERSION_PATTERN.subn(
        rf"\g<1>{new_version}\g<3>",
        contents,
        count=1,
    )
    if replacements != 1:
        raise ValueError("Could not update project.version in pyproject.toml")
    pyproject_path.write_text(updated_contents)


def ensure_tag_does_not_exist(tag_name: str) -> None:
    """Ensure a Git release tag does not already exist.

    Args:
        tag_name: The Git tag name to validate.

    Returns:
        None.

    Raises:
        RuntimeError: If the tag already exists.
        subprocess.CalledProcessError: If Git cannot be queried.
    """

    result = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag_name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise RuntimeError(f"Git tag {tag_name!r} already exists.")


def create_release_tag(tag_name: str) -> None:
    """Create an annotated Git tag for the current release version.

    Args:
        tag_name: The semantic version tag in `vX.Y.Z` format.

    Returns:
        None.

    Raises:
        RuntimeError: If the tag already exists.
        subprocess.CalledProcessError: If the Git tag command fails.
    """

    ensure_tag_does_not_exist(tag_name)
    subprocess.run(
        ["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"],
        check=True,
    )


def main() -> int:
    """Run the requested release helper command.

    Returns:
        Process exit code, where `0` means success.

    Raises:
        FileNotFoundError: If the requested `pyproject.toml` file is missing.
        ValueError: If version data is invalid or cannot be updated safely.
        RuntimeError: If release tag creation would overwrite an existing tag.
        subprocess.CalledProcessError: If a Git command fails.
    """

    args = parse_args()

    if args.command == "current-version":
        print(read_version(args.pyproject))
        return 0

    if args.command == "bump":
        current_version = read_version(args.pyproject)
        next_version = bump_version(current_version, args.part)
        write_version(args.pyproject, next_version)
        print(next_version)
        return 0

    current_version = read_version(args.pyproject)
    tag_name = f"v{current_version}"
    if args.dry_run:
        print(tag_name)
        return 0

    create_release_tag(tag_name)
    print(tag_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
