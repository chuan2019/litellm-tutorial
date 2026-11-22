"""Copy the released edition's page and self-test to the blog, with file links pointing at GitHub at the release tag.

Usage: publish_blog.py BLOG_REPO
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

from check_versions import ROOT, check


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(blog):
    tutorial, litellm = check()
    tag = f"v{tutorial}-litellm{litellm}"
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("working tree has uncommitted changes; commit and tag first")
    if tag not in git("tag", "--points-at", "HEAD").split():
        sys.exit(f"HEAD is not tagged {tag}; the published links would point at other content")
    slug = re.search(r"github\.com[:/](.+?)(?:\.git)?$", git("remote", "get-url", "origin")).group(1)
    local = {"exercises/exam.html"}

    def rewrite(m):
        target, frag = m.group(1).partition("#")[::2]
        if target in local:
            return m.group(0)
        kind = "tree" if (ROOT / target).is_dir() else "blob"
        if not (ROOT / target).exists():
            sys.exit(f"TUTORIAL.html links to missing file {target}")
        url = f"https://github.com/{slug}/{kind}/{tag}/{target.rstrip('/')}" + (f"#{frag}" if frag else "")
        return f'href="{url}" target="_blank" rel="noopener"'

    page = (ROOT / "TUTORIAL.html").read_text()
    page = re.sub(r'href="(?!https?:|#|mailto:)([^"]+)"', rewrite, page)
    page, n = re.subn(r'(<p class="byline">.*?)(</p>)',
                      rf'\1 · <a href="https://github.com/{slug}/tree/{tag}" target="_blank" rel="noopener">Source on GitHub</a>\2',
                      page, count=1)
    if n != 1:
        sys.exit("byline not found in TUTORIAL.html")

    dest = Path(blog).resolve() / "tutorials" / "litellm" / litellm
    (dest / "exercises").mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(page)
    shutil.copyfile(ROOT / "exercises" / "exam.html", dest / "exercises" / "exam.html")
    print(f"published {tag} to {dest}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
