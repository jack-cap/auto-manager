"""Property-based tests for OCR service functionality.

Uses Hypothesis for property-based testing to validate universal correctness
properties across all valid inputs.

Feature: manager-io-bookkeeper

Properties tested:
- Property 6: Document OCR Processing
- Property 7: Character Normalization
- Property 8: Multi-Page PDF Processing

**Validates: Requirements 3.1, 3.2, 3.4, 3.7, 3.8**
"""

import asyncio
import io
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hyp_settings, strategies as st, assume
from PIL import Image

from app.services.ocr import OCRService, OCRResult


# =============================================================================
# Custom Strategies
# =============================================================================

# Full-width ASCII character strategy (U+FF01 to U+FF5E)
fullwidth_char_strategy = st.integers(
    min_value=0xFF01, max_value=0xFF5E
).map(chr)

# Half-width ASCII character strategy (U+0021 to U+007E)
halfwidth_char_strategy = st.integers(
    min_value=0x0021, max_value=0x007E
).map(chr)

# Mixed text strategy with full-width and regular characters
mixed_text_strategy = st.text(
    alphabet=st.sampled_from(
        # Regular ASCII
        list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,!?-") +
        # Full-width ASCII (some examples)
        list("ＡＢＣＤＥＦＧ０１２３４５６７８９　，．！？")
    ),
    min_size=1,
    max_size=200,
)

# Page count strategy for multi-page PDFs
page_count_strategy = st.integers(min_value=1, max_value=10)


# =============================================================================
# Helper Functions
# =============================================================================

def create_test_image(width: int = 100, height: int = 100, color: str = "white") -> bytes:
    """Create a simple test image.
    
    Args:
        width: Image width in pixels
        height: Image height in pixels
        color: Background color
        
    Returns:
        JPEG image bytes
    """
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def create_mock_pdf_pages(num_pages: int) -> List[Image.Image]:
    """Create mock PDF page images.
    
    Args:
        num_pages: Number of pages to create
        
    Returns:
        List of PIL Image objects
    """
    return [
        Image.new("RGB", (100, 100), f"#{i:02x}{i:02x}{i:02x}")
        for i in range(num_pages)
    ]


# =============================================================================
# Property 6: Document OCR Processing
# =============================================================================


class TestDocumentOCRProcessingProperty:
    """Property 6: Document OCR Processing
    
    For any valid document (PDF or image) containing text, processing through
    OCRService SHALL return an OCRResult containing non-empty extracted text.
    
    **Validates: Requirements 3.1, 3.2, 3.4**
    """
    
    @given(
        extracted_text=st.text(min_size=1, max_size=500).filter(lambda x: len(x.strip()) > 0),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_extract_text_returns_ocr_result(
        self,
        extracted_text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 6: Document OCR Processing
        
        For any valid image, extract_text SHALL return an OCRResult.
        **Validates: Requirements 3.1, 3.2**
        """
        async def run_test():
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create test image
            image_data = create_test_image()
            
            # Mock the LMStudio API response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": extracted_text
                        }
                    }
                ]
            }
            
            try:
                with patch.object(ocr, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_get_client.return_value = mock_client
                    
                    result = await ocr.extract_text(image_data)
                    
                    # Property: result is an OCRResult
                    assert isinstance(result, OCRResult), \
                        "extract_text must return an OCRResult"
                    
                    # Property: result contains text
                    assert result.text is not None, \
                        "OCRResult must have text attribute"
                    
                    # Property: result has success indicator
                    assert hasattr(result, "success"), \
                        "OCRResult must have success property"
            finally:
                await ocr.close()
        
        asyncio.run(run_test())
    
    @given(
        extracted_text=st.text(min_size=1, max_size=500).filter(lambda x: len(x.strip()) > 0),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_extract_text_returns_non_empty_text_on_success(
        self,
        extracted_text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 6: Document OCR Processing
        
        For any valid image with text, successful OCR SHALL return non-empty text.
        **Validates: Requirements 3.1, 3.4**
        """
        async def run_test():
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create test image
            image_data = create_test_image()
            
            # Mock successful API response with text
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": extracted_text
                        }
                    }
                ]
            }
            
            try:
                with patch.object(ocr, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_get_client.return_value = mock_client
                    
                    result = await ocr.extract_text(image_data)
                    
                    # Property: successful OCR returns non-empty text
                    if result.success:
                        assert len(result.text) > 0, \
                            "Successful OCR must return non-empty text"
            finally:
                await ocr.close()
        
        asyncio.run(run_test())
    
    @given(
        image_width=st.integers(min_value=10, max_value=500),
        image_height=st.integers(min_value=10, max_value=500),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_extract_text_handles_various_image_sizes(
        self,
        image_width: int,
        image_height: int,
    ):
        """Feature: manager-io-bookkeeper, Property 6: Document OCR Processing
        
        For any valid image size, extract_text SHALL process without error.
        **Validates: Requirements 3.1, 3.2**
        """
        async def run_test():
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create test image with specified dimensions
            image_data = create_test_image(width=image_width, height=image_height)
            
            # Mock successful API response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": "Test text"
                        }
                    }
                ]
            }
            
            try:
                with patch.object(ocr, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_get_client.return_value = mock_client
                    
                    result = await ocr.extract_text(image_data)
                    
                    # Property: OCR processes any valid image size
                    assert isinstance(result, OCRResult), \
                        f"OCR must handle image size {image_width}x{image_height}"
            finally:
                await ocr.close()
        
        asyncio.run(run_test())


# =============================================================================
# Property 7: Character Normalization
# =============================================================================


class TestCharacterNormalizationProperty:
    """Property 7: Character Normalization
    
    For any string containing full-width characters, normalizing through
    OCRService.normalize_text SHALL convert all full-width ASCII characters
    (U+FF01-U+FF5E) to their half-width equivalents.
    
    **Validates: Requirements 3.8**
    """
    
    @given(
        fullwidth_char=fullwidth_char_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_fullwidth_ascii_converted_to_halfwidth(
        self,
        fullwidth_char: str,
    ):
        """Feature: manager-io-bookkeeper, Property 7: Character Normalization
        
        Full-width ASCII characters (U+FF01-U+FF5E) SHALL be converted to half-width.
        **Validates: Requirements 3.8**
        """
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra",
        )
        
        # Normalize the full-width character
        result = ocr.normalize_text(fullwidth_char)
        
        # Property: result is a single character
        assert len(result) == 1, \
            f"Normalized result should be single character, got '{result}'"
        
        # Property: result is in half-width ASCII range
        code_point = ord(result)
        assert 0x0021 <= code_point <= 0x007E, \
            f"Normalized character should be half-width ASCII, got U+{code_point:04X}"
        
        # Property: the conversion is correct (offset by 0xFEE0)
        expected_code = ord(fullwidth_char) - 0xFEE0
        assert code_point == expected_code, \
            f"Expected U+{expected_code:04X}, got U+{code_point:04X}"
    
    @given(
        text=mixed_text_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_normalize_text_preserves_length_for_ascii(
        self,
        text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 7: Character Normalization
        
        Normalization SHALL preserve text length (1:1 character mapping).
        **Validates: Requirements 3.8**
        """
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra",
        )
        
        result = ocr.normalize_text(text)
        
        # Property: length is preserved
        assert len(result) == len(text), \
            f"Normalization should preserve length: {len(text)} -> {len(result)}"
    
    @given(
        halfwidth_text=st.text(
            alphabet=st.characters(min_codepoint=0x0020, max_codepoint=0x007E),
            min_size=1,
            max_size=100,
        ),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_halfwidth_text_unchanged(
        self,
        halfwidth_text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 7: Character Normalization
        
        Half-width ASCII text SHALL remain unchanged after normalization.
        **Validates: Requirements 3.8**
        """
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra",
        )
        
        result = ocr.normalize_text(halfwidth_text)
        
        # Property: half-width text is unchanged
        assert result == halfwidth_text, \
            f"Half-width text should be unchanged: '{halfwidth_text}' -> '{result}'"
    
    def test_fullwidth_space_converted_to_regular_space(self):
        """Feature: manager-io-bookkeeper, Property 7: Character Normalization
        
        Full-width space (U+3000) SHALL be converted to regular space.
        **Validates: Requirements 3.8**
        """
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra",
        )
        
        # Full-width space is U+3000
        fullwidth_space = '\u3000'
        result = ocr.normalize_text(fullwidth_space)
        
        # Property: full-width space becomes regular space
        assert result == ' ', \
            f"Full-width space should become regular space, got '{result}'"
    
    def test_fullwidth_yen_converted_to_halfwidth(self):
        """Feature: manager-io-bookkeeper, Property 7: Character Normalization
        
        Full-width yen sign (U+FFE5) SHALL be converted to half-width yen.
        **Validates: Requirements 3.8**
        """
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra",
        )
        
        # Full-width yen is U+FFE5
        fullwidth_yen = '\uFFE5'
        result = ocr.normalize_text(fullwidth_yen)
        
        # Property: full-width yen becomes half-width yen (U+00A5)
        assert result == '\u00A5', \
            f"Full-width yen should become half-width yen, got '{result}'"
    
    @given(
        text=st.text(min_size=0, max_size=100),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_normalize_text_handles_empty_and_any_text(
        self,
        text: str,
    ):
        """Feature: manager-io-bookkeeper, Property 7: Character Normalization
        
        normalize_text SHALL handle any input text without error.
        **Validates: Requirements 3.8**
        """
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra",
        )
        
        # Property: normalize_text handles any input
        result = ocr.normalize_text(text)
        
        # Property: result is a string
        assert isinstance(result, str), \
            f"normalize_text must return a string, got {type(result)}"


# =============================================================================
# Property 8: Multi-Page PDF Processing
# =============================================================================


class TestMultiPagePDFProcessingProperty:
    """Property 8: Multi-Page PDF Processing
    
    For any multi-page PDF document, processing through OCRService SHALL
    return extracted text from all pages combined.
    
    **Validates: Requirements 3.7**
    """
    
    @given(
        num_pages=page_count_strategy,
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_pdf_processing_returns_correct_page_count(
        self,
        num_pages: int,
    ):
        """Feature: manager-io-bookkeeper, Property 8: Multi-Page PDF Processing
        
        For a PDF with N pages, OCRResult.pages SHALL equal N.
        **Validates: Requirements 3.7**
        """
        async def run_test():
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create mock PDF pages
            mock_pages = create_mock_pdf_pages(num_pages)
            
            # Mock pdf2image conversion
            with patch("app.services.ocr.convert_from_bytes") as mock_convert:
                mock_convert.return_value = mock_pages
                
                # Mock the extract_text method to return text for each page
                async def mock_extract_text(image_data):
                    return OCRResult(
                        text="Page text",
                        pages=1,
                        page_texts=["Page text"],
                    )
                
                with patch.object(ocr, "extract_text", side_effect=mock_extract_text):
                    # Create dummy PDF data
                    pdf_data = b"%PDF-1.4 dummy pdf content"
                    
                    result = await ocr.extract_from_pdf(pdf_data)
                    
                    # Property: page count matches input
                    assert result.pages == num_pages, \
                        f"Expected {num_pages} pages, got {result.pages}"
        
        asyncio.run(run_test())
    
    @given(
        num_pages=page_count_strategy,
        page_texts=st.lists(
            st.text(min_size=1, max_size=100).filter(lambda x: len(x.strip()) > 0),
            min_size=1,
            max_size=10,
        ),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_pdf_processing_combines_all_page_texts(
        self,
        num_pages: int,
        page_texts: List[str],
    ):
        """Feature: manager-io-bookkeeper, Property 8: Multi-Page PDF Processing
        
        For a multi-page PDF, all page texts SHALL be combined in the result.
        **Validates: Requirements 3.7**
        """
        async def run_test():
            # Use the minimum of num_pages and page_texts length
            actual_pages = min(num_pages, len(page_texts))
            texts_to_use = page_texts[:actual_pages]
            
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create mock PDF pages
            mock_pages = create_mock_pdf_pages(actual_pages)
            
            # Track which page we're on
            page_index = [0]
            
            # Mock pdf2image conversion
            with patch("app.services.ocr.convert_from_bytes") as mock_convert:
                mock_convert.return_value = mock_pages
                
                # Mock the extract_text method to return specific text for each page
                async def mock_extract_text(image_data):
                    idx = page_index[0]
                    page_index[0] += 1
                    text = texts_to_use[idx] if idx < len(texts_to_use) else ""
                    return OCRResult(
                        text=text,
                        pages=1,
                        page_texts=[text],
                    )
                
                with patch.object(ocr, "extract_text", side_effect=mock_extract_text):
                    # Create dummy PDF data
                    pdf_data = b"%PDF-1.4 dummy pdf content"
                    
                    result = await ocr.extract_from_pdf(pdf_data)
                    
                    # Property: all page texts are present in combined result
                    for text in texts_to_use:
                        assert text in result.text, \
                            f"Page text '{text}' should be in combined result"
                    
                    # Property: page_texts list has correct length
                    assert len(result.page_texts) == actual_pages, \
                        f"Expected {actual_pages} page texts, got {len(result.page_texts)}"
        
        asyncio.run(run_test())
    
    @given(
        num_pages=st.integers(min_value=2, max_value=5),
    )
    @hyp_settings(max_examples=20, deadline=None)
    def test_pdf_processing_preserves_page_order(
        self,
        num_pages: int,
    ):
        """Feature: manager-io-bookkeeper, Property 8: Multi-Page PDF Processing
        
        Page texts SHALL be combined in order (page 1, page 2, ..., page N).
        **Validates: Requirements 3.7**
        """
        async def run_test():
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create mock PDF pages
            mock_pages = create_mock_pdf_pages(num_pages)
            
            # Track page order
            page_index = [0]
            
            # Mock pdf2image conversion
            with patch("app.services.ocr.convert_from_bytes") as mock_convert:
                mock_convert.return_value = mock_pages
                
                # Mock the extract_text method with numbered page text
                async def mock_extract_text(image_data):
                    idx = page_index[0]
                    page_index[0] += 1
                    text = f"PAGE_{idx + 1}_CONTENT"
                    return OCRResult(
                        text=text,
                        pages=1,
                        page_texts=[text],
                    )
                
                with patch.object(ocr, "extract_text", side_effect=mock_extract_text):
                    # Create dummy PDF data
                    pdf_data = b"%PDF-1.4 dummy pdf content"
                    
                    result = await ocr.extract_from_pdf(pdf_data)
                    
                    # Property: pages are in order
                    for i in range(num_pages):
                        expected_marker = f"PAGE_{i + 1}_CONTENT"
                        assert expected_marker in result.text, \
                            f"Page {i + 1} marker should be in result"
                    
                    # Property: page_texts list is in order
                    for i, page_text in enumerate(result.page_texts):
                        expected_marker = f"PAGE_{i + 1}_CONTENT"
                        assert page_text == expected_marker, \
                            f"Page {i + 1} text should be '{expected_marker}', got '{page_text}'"
        
        asyncio.run(run_test())
    
    def test_pdf_processing_handles_partial_failures(self):
        """Feature: manager-io-bookkeeper, Property 8: Multi-Page PDF Processing
        
        If some pages fail OCR, successful pages SHALL still be included.
        **Validates: Requirements 3.7**
        """
        async def run_test():
            ocr = OCRService(
                lmstudio_url="http://localhost:1234/v1",
                model_name="chandra",
            )
            
            # Create 3 mock PDF pages
            mock_pages = create_mock_pdf_pages(3)
            
            # Track page order
            page_index = [0]
            
            # Mock pdf2image conversion
            with patch("app.services.ocr.convert_from_bytes") as mock_convert:
                mock_convert.return_value = mock_pages
                
                # Mock extract_text - page 2 fails
                async def mock_extract_text(image_data):
                    idx = page_index[0]
                    page_index[0] += 1
                    
                    if idx == 1:  # Page 2 fails
                        return OCRResult(
                            text="",
                            pages=1,
                            page_texts=[""],
                            error="OCR failed for this page",
                        )
                    else:
                        text = f"Page {idx + 1} text"
                        return OCRResult(
                            text=text,
                            pages=1,
                            page_texts=[text],
                        )
                
                with patch.object(ocr, "extract_text", side_effect=mock_extract_text):
                    # Create dummy PDF data
                    pdf_data = b"%PDF-1.4 dummy pdf content"
                    
                    result = await ocr.extract_from_pdf(pdf_data)
                    
                    # Property: successful pages are included
                    assert "Page 1 text" in result.text, \
                        "Page 1 text should be in result"
                    assert "Page 3 text" in result.text, \
                        "Page 3 text should be in result"
                    
                    # Property: page count is still correct
                    assert result.pages == 3, \
                        "Page count should still be 3"
        
        asyncio.run(run_test())
