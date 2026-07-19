#!/usr/bin/env python3
"""Convert a published WordPress post into dev.to-ready markdown.

The LIVE post is the source of truth (it may have edits/images not in the local
markdown). This fetches the post HTML, converts the body to markdown, restores
blockquotes, rewrites images to full-resolution WordPress URLs, and prepends
dev.to front matter with a canonical_url back to the original.

Usage:
    python3 to_devto.py <post-url> [--tags ai,ruby,productivity]

Run from your blog directory. Writes drafts/<slug>.devto.md in the current
working directory and copies it to the clipboard (pbcopy, macOS only).
"""

import html
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

PROJECT_DIR = os.getcwd()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 30

# Curly punctuation -> plain ASCII (keeps the author's no-fancy-punctuation
# style). Built with chr() so this source file stays pure ASCII.
RSQUO, LSQUO = chr(0x2019), chr(0x2018)
LDQUO, RDQUO = chr(0x201C), chr(0x201D)
ENDASH, EMDASH = chr(0x2013), chr(0x2014)
NBSP = chr(0xA0)
PUNCT = {
    RSQUO: "'", LSQUO: "'",
    LDQUO: '"', RDQUO: '"',
    ENDASH: "-", EMDASH: "-",
    NBSP: " ",
}
DASH_CLASS = "[|" + ENDASH + EMDASH + "-]"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def meta(doc, *keys):
    for k in keys:
        m = re.search(
            rf'<meta[^>]+(?:name|property)="{re.escape(k)}"[^>]+content="([^"]*)"',
            doc,
        ) or re.search(
            rf'<meta[^>]+content="([^"]*)"[^>]+(?:name|property)="{re.escape(k)}"',
            doc,
        )
        if m:
            return html.unescape(m.group(1))
    return ""


def normalize(s):
    for a, b in PUNCT.items():
        s = s.replace(a, b)
    return s


def inline(s):
    s = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", s, flags=re.DOTALL)
    s = re.sub(r"<strong>(.*?)</strong>", r"**\1**", s, flags=re.DOTALL)
    s = re.sub(r"<em>(.*?)</em>", r"*\1*", s, flags=re.DOTALL)
    s = re.sub(r'<a [^>]*?href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", s, flags=re.DOTALL)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return normalize(html.unescape(s)).strip()


def strip_size(url):
    return re.sub(r"-\d+x\d+(\.\w+)$", r"\1", url)


def convert_body(body):
    block_re = re.compile(
        r"<h([1-6])[^>]*>(.*?)</h\1>"
        r"|<pre[^>]*>(.*?)</pre>"
        r"|<ul[^>]*>(.*?)</ul>"
        r"|<ol[^>]*>(.*?)</ol>"
        r"|<figure[^>]*>(.*?)</figure>"
        r"|<p[^>]*>(.*?)</p>",
        re.DOTALL,
    )
    out = []
    for mo in block_re.finditer(body):
        hlevel, htext, pre, ul, ol, fig, p = mo.groups()
        if htext is not None:
            out.append("#" * int(hlevel) + " " + inline(htext))
        elif pre is not None:
            lang = re.search(r'<code[^>]*class="[^"]*language-([\w-]+)', pre)
            code = re.sub(r"</?code[^>]*>", "", pre)
            code = html.unescape(code).strip("\n")
            out.append(f"```{lang.group(1) if lang else ''}\n{code}\n```")
        elif ul is not None or ol is not None:
            raw = ul if ul is not None else ol
            items = re.findall(r"<li[^>]*>(.*?)</li>", raw, re.DOTALL)
            bullet = "- " if ul is not None else "1. "
            out.append("\n".join(bullet + inline(it) for it in items))
        elif fig is not None:
            src = re.search(r'src="([^"]+)"', fig)
            alt = re.search(r'alt="([^"]*)"', fig)
            cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", fig, re.DOTALL)
            if not src:
                continue
            alt_txt = html.unescape(alt.group(1)) if alt else ""
            block = f"![{alt_txt}]({strip_size(src.group(1))})"
            if cap:
                block += "\n*" + inline(cap.group(1)) + "*"
            out.append(block)
        elif p is not None:
            t = inline(p)
            if not t:
                continue
            if t.startswith(">"):
                lines = [ln if ln.strip().startswith(">") else "> " + ln
                         for ln in t.split("\n")]
                out.append("\n".join(lines))
            else:
                out.append(t)
    return "\n\n".join(out)


def local_excerpt(slug):
    pub = os.path.join(PROJECT_DIR, "published")
    if not os.path.isdir(pub):
        return ""
    for name in os.listdir(pub):
        if slug in name:
            with open(os.path.join(pub, name), encoding="utf-8") as f:
                m = re.search(r'^excerpt:\s*"?(.*?)"?\s*$', f.read(), re.MULTILINE)
                if m:
                    return m.group(1)
    return ""


def strip_title_suffix(title):
    # Drop a trailing " | Site Name" or " - Site Name" segment.
    return re.sub(r"\s*" + DASH_CLASS + r"\s*[^|]*$", "", title).strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: to_devto.py <post-url> [--tags a,b,c,d]")
        sys.exit(1)
    url = sys.argv[1].rstrip("/")
    if not url.startswith("https://"):
        print("Error: post URL must start with https://")
        sys.exit(1)
    tags = ""
    if "--tags" in sys.argv:
        tags = ", ".join(sys.argv[sys.argv.index("--tags") + 1].split(",")).strip()

    path = url.split("?")[0].split("#")[0].rstrip("/")
    slug = re.sub(r"[^a-z0-9-]", "", path.rsplit("/", 1)[-1].lower())
    if not slug:
        print("Error: could not derive a slug from the URL")
        sys.exit(1)

    try:
        doc = fetch(url)
    except urllib.error.URLError as e:
        print(f"Error: could not fetch {url}: {e}")
        sys.exit(1)

    title = strip_title_suffix(meta(doc, "og:title") or "")
    if not title:
        t = re.search(r"<title>(.*?)</title>", doc, re.DOTALL)
        title = strip_title_suffix(html.unescape(t.group(1))) if t else slug
    description = meta(doc, "description", "og:description") or local_excerpt(slug)
    cover = meta(doc, "og:image")

    m = re.search(
        r'class="entry-content[^"]*"(.*?)(?:<footer|id="comments"|class="post-tags")',
        doc, re.DOTALL,
    )
    if not m:
        print("Error: could not locate entry-content body")
        sys.exit(1)
    bodymd = convert_body(m.group(1))

    fm = (
        "---\n"
        f"title: {title}\n"
        "published: false\n"
        f"description: {normalize(description)}\n"
    )
    if tags:
        fm += f"tags: {tags}\n"
    fm += f"canonical_url: {url}/\n"
    if cover:
        fm += f"cover_image: {cover}\n"
    fm += "---\n\n"

    final = fm + bodymd + "\n"
    os.makedirs(os.path.join(PROJECT_DIR, "drafts"), exist_ok=True)
    outpath = os.path.join(PROJECT_DIR, "drafts", f"{slug}.devto.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(final)

    try:
        subprocess.run(["pbcopy"], input=final.encode("utf-8"), check=True)
        copied = " and copied to clipboard"
    except Exception:
        copied = " (pbcopy unavailable)"

    images = bodymd.count("![")
    quotes = sum(1 for b in bodymd.split("\n\n") if b.startswith(">"))
    print(f"Wrote {outpath}{copied}")
    print(f"  Title:  {title}")
    print(f"  Images: {images}  Blockquotes: {quotes}")
    print(f"  Tags:   {tags or '(none)'}")


if __name__ == "__main__":
    main()
