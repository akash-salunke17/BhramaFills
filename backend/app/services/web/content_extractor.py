"""Content extraction engine utilizing BeautifulSoup to isolate readable text and metadata."""

from datetime import datetime, timezone
import hashlib
import re

from bs4 import BeautifulSoup, Comment

from app.services.web.schemas import HeadingItem, WebExtractResponse

# HTML elements to strip completely before extracting text
UNWANTED_ELEMENTS = [
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    "svg",
    "audio",
    "video",
    "canvas",
    "iframe",
    "embed",
    "object",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "template",
]


class WebContentExtractor:
    """Extracts clean text, structured headings, and metadata from raw HTML."""

    @classmethod
    def extract(
        cls,
        html: str,
        original_url: str,
        final_url: str,
        status_code: int = 200,
        redirect_count: int = 0,
    ) -> WebExtractResponse:
        """Parse HTML string and generate a structured WebExtractResponse."""
        soup = BeautifulSoup(html, "html.parser")

        # 1. Extract metadata before destructive tag stripping
        title = cls._extract_title(soup)
        meta_description = cls._extract_meta_description(soup)
        author = cls._extract_author(soup)
        language = cls._extract_language(soup)
        canonical_url = cls._extract_canonical_url(soup)

        # 2. Extract structured headings
        headings = cls._extract_headings(soup)

        # 3. Strip comments and unwanted noisy tags
        for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()

        for tag_name in UNWANTED_ELEMENTS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 4. Extract distinct paragraphs
        paragraphs = cls._extract_paragraphs(soup)

        # 5. Extract and normalize clean body text
        # If paragraphs are available, join them; otherwise fallback to body/soup text
        if paragraphs:
            clean_text = "\n\n".join(paragraphs)
        else:
            raw_text = soup.get_text(separator="\n", strip=True)
            clean_text = re.sub(r"\n{3,}", "\n\n", raw_text)

        clean_text = clean_text.strip()
        character_count = len(clean_text)
        word_count = len(clean_text.split()) if clean_text else 0
        content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

        return WebExtractResponse(
            url=original_url,
            final_url=final_url,
            status_code=status_code,
            title=title,
            meta_description=meta_description,
            author=author,
            language=language,
            canonical_url=canonical_url,
            clean_text=clean_text,
            headings=headings,
            paragraphs=paragraphs,
            word_count=word_count,
            character_count=character_count,
            content_hash=content_hash,
            redirect_count=redirect_count,
            extracted_at=datetime.now(timezone.utc),
        )

    @classmethod
    def _extract_title(cls, soup: BeautifulSoup) -> str | None:
        """Extract title from <title>, OpenGraph title, or primary <h1>."""
        # 1. <title>
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()
            if title:
                return title

        # 2. OpenGraph og:title
        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            if title:
                return title

        # 3. <h1>
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
            if title:
                return title

        return None

    @classmethod
    def _extract_meta_description(cls, soup: BeautifulSoup) -> str | None:
        """Extract description from <meta name='description'> or OpenGraph."""
        for attr in ("description", "og:description", "twitter:description"):
            tag = soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"property": attr})
            if tag and tag.get("content"):
                desc = tag["content"].strip()
                if desc:
                    return desc
        return None

    @classmethod
    def _extract_author(cls, soup: BeautifulSoup) -> str | None:
        """Extract author from meta tags or rel='author'."""
        for attr in ("author", "article:author", "twitter:creator"):
            tag = soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"property": attr})
            if tag and tag.get("content"):
                author = tag["content"].strip()
                if author:
                    return author

        author_tag = soup.find(attrs={"rel": "author"})
        if author_tag:
            author = author_tag.get_text(strip=True)
            if author:
                return author

        return None

    @classmethod
    def _extract_language(cls, soup: BeautifulSoup) -> str | None:
        """Extract language from <html> lang attribute or meta content-language."""
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].strip()
            if lang:
                return lang

        meta_lang = soup.find("meta", attrs={"http-equiv": re.compile(r"^content-language$", re.I)})
        if meta_lang and meta_lang.get("content"):
            lang = meta_lang["content"].strip()
            if lang:
                return lang

        return None

    @classmethod
    def _extract_canonical_url(cls, soup: BeautifulSoup) -> str | None:
        """Extract canonical URL from <link rel='canonical'>."""
        link_tag = soup.find("link", attrs={"rel": "canonical"})
        if link_tag and link_tag.get("href"):
            canonical = link_tag["href"].strip()
            if canonical:
                return canonical
        return None

    @classmethod
    def _extract_headings(cls, soup: BeautifulSoup) -> list[HeadingItem]:
        """Extract headings h1-h6 in document appearance order."""
        headings: list[HeadingItem] = []
        for tag in soup.find_all(re.compile(r"^h[1-6]$")):
            text = tag.get_text(strip=True)
            if text:
                level = int(tag.name[1])
                headings.append(HeadingItem(level=level, text=text))
        return headings

    @classmethod
    def _extract_paragraphs(cls, soup: BeautifulSoup) -> list[str]:
        """Extract meaningful, non-empty paragraph blocks."""
        paragraphs: list[str] = []
        for p in soup.find_all(["p", "blockquote"]):
            text = p.get_text(strip=True)
            # Filter out boilerplate, zero-length, or single-character noise
            if text and len(text) > 20:
                paragraphs.append(text)
        return paragraphs

