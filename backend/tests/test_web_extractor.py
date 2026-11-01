"""Unit tests for BeautifulSoup-based HTML content extraction."""

import pytest

from app.services.web.content_extractor import WebContentExtractor


SAMPLE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Quantum Computing Breakthrough Announced in 2026</title>
    <meta name="description" content="Researchers at MIT announced a major breakthrough in fault-tolerant quantum computing architectures.">
    <meta name="author" content="Dr. Jane Doe">
    <link rel="canonical" href="https://example.org/articles/quantum-2026">
    <style>body { font-family: sans-serif; }</style>
    <script>console.log("tracking code");</script>
</head>
<body>
    <header>
        <nav><a href="/">Home</a><a href="/news">News</a></nav>
    </header>
    
    <main>
        <h1>Quantum Computing Breakthrough Announced in 2026</h1>
        <p>A collaborative research group led by MIT and Oxford physicists announced a major advance in quantum error correction.</p>
        
        <h2>Hardware Architecture and Logical Qubits</h2>
        <p>The team successfully demonstrated 100 logical qubits operating under fault-tolerant thresholds with sub-microsecond cycle times.</p>
        
        <h2>Implications for Cryptographic Algorithms</h2>
        <p>While practical decryption of RSA remains years away, this demonstration confirms the viability of modular neutral-atom quantum processors.</p>
        
        <aside>
            <p>Related links and sidebar advertisements</p>
        </aside>
    </main>
    
    <footer>
        <p>Copyright 2026 Science Daily. All rights reserved.</p>
    </footer>
</body>
</html>
"""


def test_content_extractor_metadata_parsing():
    """Verify title, description, author, language, and canonical URL extraction."""
    extracted = WebContentExtractor.extract(
        html=SAMPLE_HTML,
        original_url="https://example.org/articles/quantum-2026",
        final_url="https://example.org/articles/quantum-2026",
    )

    assert extracted.title == "Quantum Computing Breakthrough Announced in 2026"
    assert "fault-tolerant quantum computing" in extracted.meta_description
    assert extracted.author == "Dr. Jane Doe"
    assert extracted.language == "en"
    assert extracted.canonical_url == "https://example.org/articles/quantum-2026"


def test_content_extractor_noise_stripping():
    """Verify scripts, styles, nav, footer, header, and aside are stripped."""
    extracted = WebContentExtractor.extract(
        html=SAMPLE_HTML,
        original_url="https://example.org/articles/quantum-2026",
        final_url="https://example.org/articles/quantum-2026",
    )

    # Ensure unwanted tags are decomposed
    assert "tracking code" not in extracted.clean_text
    assert "font-family" not in extracted.clean_text
    assert "Home" not in extracted.clean_text  # In <nav>
    assert "Copyright 2026" not in extracted.clean_text  # In <footer>
    assert "sidebar advertisements" not in extracted.clean_text  # In <aside>


def test_content_extractor_headings_and_paragraphs():
    """Verify structured headings and paragraphs are properly collected."""
    extracted = WebContentExtractor.extract(
        html=SAMPLE_HTML,
        original_url="https://example.org/articles/quantum-2026",
        final_url="https://example.org/articles/quantum-2026",
    )

    # Check headings
    assert len(extracted.headings) == 3
    assert extracted.headings[0].level == 1
    assert "Breakthrough Announced" in extracted.headings[0].text
    assert extracted.headings[1].level == 2
    assert "Hardware Architecture" in extracted.headings[1].text

    # Check paragraphs
    assert len(extracted.paragraphs) == 3
    assert "collaborative research group" in extracted.paragraphs[0]
    assert "demonstrated 100 logical qubits" in extracted.paragraphs[1]


def test_content_extractor_counts_and_hash():
    """Verify word count, character count, and SHA-256 hash calculation."""
    extracted = WebContentExtractor.extract(
        html=SAMPLE_HTML,
        original_url="https://example.org/articles/quantum-2026",
        final_url="https://example.org/articles/quantum-2026",
    )

    assert extracted.word_count > 40
    assert extracted.character_count > 200
    assert len(extracted.content_hash) == 64
    assert extracted.status_code == 200


def test_content_extractor_opengraph_fallback():
    """Verify fallback to OpenGraph meta tags when standard HTML tags are missing."""
    og_html = """
    <html>
    <head>
        <meta property="og:title" content="OpenGraph Article Title">
        <meta property="og:description" content="OpenGraph description summary.">
        <meta property="article:author" content="Jane Specialist">
    </head>
    <body>
        <p>This is a valid article paragraph providing factual statements for testing.</p>
    </body>
    </html>
    """
    extracted = WebContentExtractor.extract(
        html=og_html,
        original_url="https://example.org/og-test",
        final_url="https://example.org/og-test",
    )
    assert extracted.title == "OpenGraph Article Title"
    assert extracted.meta_description == "OpenGraph description summary."
    assert extracted.author == "Jane Specialist"

