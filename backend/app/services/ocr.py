"""OCR Service using chandra_ocr vision model via LMStudio.

This module provides the OCRService class for extracting text from
documents (images and PDFs) using the chandra_ocr vision model.

Features:
- Text extraction from images using LMStudio's OpenAI-compatible API
- PDF to image conversion with multi-page support
- Full-width to half-width character normalization (Japanese/Chinese)
- Health check for LMStudio connectivity
"""

import base64
import io
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from pdf2image import convert_from_bytes
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class OCRResult:
    """Result from OCR text extraction.
    
    Attributes:
        text: Extracted text from the document
        confidence: Confidence score (0.0 to 1.0) if available
        pages: Number of pages processed (for PDFs)
        page_texts: List of text extracted from each page
        error: Error message if extraction failed
    """
    text: str
    confidence: Optional[float] = None
    pages: int = 1
    page_texts: List[str] = field(default_factory=list)
    error: Optional[str] = None
    
    @property
    def success(self) -> bool:
        """Check if OCR extraction was successful."""
        return self.error is None and len(self.text) > 0


# =============================================================================
# Exceptions
# =============================================================================


class OCRError(Exception):
    """Base exception for OCR errors."""
    pass


class OCRConnectionError(OCRError):
    """Raised when connection to LMStudio fails."""
    pass


class OCRProcessingError(OCRError):
    """Raised when OCR processing fails."""
    pass


class OCRModelNotFoundError(OCRError):
    """Raised when the OCR model is not available."""
    pass


# =============================================================================
# OCR Service
# =============================================================================


class OCRService:
    """Service for OCR text extraction using chandra_ocr via LMStudio.
    
    Uses LMStudio's OpenAI-compatible API to send images to the chandra_ocr
    vision model for text extraction. Supports both direct image processing
    and PDF conversion.
    
    Example:
        ```python
        ocr = OCRService(
            lmstudio_url="http://localhost:1234/v1",
            model_name="chandra"
        )
        
        # Check connectivity
        if await ocr.health_check():
            # Extract text from image
            with open("receipt.jpg", "rb") as f:
                result = await ocr.extract_text(f.read())
            print(result.text)
        ```
    """
    
    # Default configuration
    DEFAULT_TIMEOUT = 120.0  # seconds - OCR can take time
    MAX_IMAGE_SIZE = 4096  # Max dimension for image resizing
    JPEG_QUALITY = 95  # Quality for JPEG compression
    
    # Full-width to half-width character mapping range
    # Full-width ASCII variants: U+FF01 to U+FF5E
    # Maps to standard ASCII: U+0021 to U+007E
    FULLWIDTH_START = 0xFF01
    FULLWIDTH_END = 0xFF5E
    HALFWIDTH_OFFSET = 0xFEE0  # Difference between full-width and half-width
    
    def __init__(
        self,
        lmstudio_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """Initialize OCRService.
        
        Args:
            lmstudio_url: LMStudio API base URL. Defaults to settings.lmstudio_url.
            model_name: Vision model name. Defaults to settings.ocr_model.
            timeout: Request timeout in seconds. Defaults to 120.
        """
        self.lmstudio_url = (lmstudio_url or settings.lmstudio_url).rstrip("/")
        self.model_name = model_name or settings.ocr_model
        self.timeout = timeout
        
        # HTTP client will be created lazily
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.
        
        Returns:
            Configured httpx.AsyncClient instance
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Content-Type": "application/json",
                },
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self) -> "OCRService":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
    
    # =========================================================================
    # Health Check
    # =========================================================================
    
    async def health_check(self) -> bool:
        """Check LMStudio connectivity and model availability.
        
        Attempts to connect to LMStudio and verify the OCR model is available.
        
        Returns:
            True if LMStudio is reachable and model is available, False otherwise
        """
        try:
            client = await self._get_client()
            
            # Try to list models to verify connectivity
            response = await client.get(f"{self.lmstudio_url}/models")
            
            if response.status_code != 200:
                logger.warning(
                    f"LMStudio health check failed: HTTP {response.status_code}"
                )
                return False
            
            # Check if our model is available
            data = response.json()
            models = data.get("data", [])
            model_ids = [m.get("id", "") for m in models]
            
            # Check if any model contains our model name
            model_available = any(
                self.model_name.lower() in model_id.lower()
                for model_id in model_ids
            )
            
            if not model_available:
                logger.warning(
                    f"OCR model '{self.model_name}' not found in LMStudio. "
                    f"Available models: {model_ids}"
                )
                # Return True if LMStudio is reachable, even if model not found
                # The model might be loaded but not listed, or use a different name
                return True
            
            logger.debug(f"LMStudio health check passed. Model '{self.model_name}' available.")
            return True
            
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to LMStudio at {self.lmstudio_url}: {e}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"LMStudio health check timed out: {e}")
            return False
        except Exception as e:
            logger.error(f"LMStudio health check failed: {e}")
            return False
    
    # =========================================================================
    # Text Normalization
    # =========================================================================
    
    def normalize_text(self, text: str) -> str:
        """Normalize full-width characters to half-width equivalents.
        
        Converts full-width ASCII characters (U+FF01-U+FF5E) commonly found
        in Japanese and Chinese text to their standard half-width ASCII
        equivalents (U+0021-U+007E).
        
        Also handles:
        - Full-width space (U+3000) to regular space
        - Full-width yen sign (U+FFE5) to half-width yen (U+00A5)
        - Full-width won sign (U+FFE6) to half-width won (U+20A9)
        
        Args:
            text: Input text potentially containing full-width characters
            
        Returns:
            Text with full-width characters converted to half-width
            
        Example:
            >>> ocr = OCRService()
            >>> ocr.normalize_text("Ｈｅｌｌｏ　Ｗｏｒｌｄ")  # Full-width
            'Hello World'
            >>> ocr.normalize_text("￥１，２３４")  # Full-width yen and numbers
            '¥1,234'
        """
        if not text:
            return text
        
        result = []
        for char in text:
            code_point = ord(char)
            
            # Convert full-width ASCII (U+FF01-U+FF5E) to half-width (U+0021-U+007E)
            if self.FULLWIDTH_START <= code_point <= self.FULLWIDTH_END:
                # Subtract offset to get half-width equivalent
                result.append(chr(code_point - self.HALFWIDTH_OFFSET))
            # Convert full-width space (U+3000) to regular space
            elif code_point == 0x3000:
                result.append(' ')
            # Convert full-width yen sign (U+FFE5) to half-width yen (U+00A5)
            elif code_point == 0xFFE5:
                result.append('\u00A5')  # Half-width yen sign ¥
            # Convert full-width won sign (U+FFE6) to half-width won (U+20A9)
            elif code_point == 0xFFE6:
                result.append('\u20A9')  # Half-width won sign ₩
            else:
                result.append(char)
        
        return ''.join(result)
    
    # =========================================================================
    # Image Processing Helpers
    # =========================================================================
    
    def _prepare_image(self, image_data: bytes) -> str:
        """Prepare image data for API submission.
        
        Resizes large images and converts to base64-encoded JPEG.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            Base64-encoded image string
            
        Raises:
            OCRProcessingError: If image cannot be processed
        """
        try:
            # Open image
            image = Image.open(io.BytesIO(image_data))
            
            # Convert to RGB if necessary (handles RGBA, P mode, etc.)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            
            # Resize if too large
            width, height = image.size
            if width > self.MAX_IMAGE_SIZE or height > self.MAX_IMAGE_SIZE:
                # Calculate new size maintaining aspect ratio
                ratio = min(self.MAX_IMAGE_SIZE / width, self.MAX_IMAGE_SIZE / height)
                new_size = (int(width * ratio), int(height * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                logger.debug(f"Resized image from {width}x{height} to {new_size[0]}x{new_size[1]}")
            
            # Convert to JPEG bytes
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=self.JPEG_QUALITY)
            jpeg_bytes = buffer.getvalue()
            
            # Encode to base64
            return base64.b64encode(jpeg_bytes).decode('utf-8')
            
        except Exception as e:
            raise OCRProcessingError(f"Failed to prepare image: {e}")
    
    def _convert_pdf_to_images(self, pdf_data: bytes) -> List[bytes]:
        """Convert PDF pages to images.
        
        Args:
            pdf_data: Raw PDF bytes
            
        Returns:
            List of image bytes, one per page
            
        Raises:
            OCRProcessingError: If PDF conversion fails
        """
        try:
            # Convert PDF to PIL Images
            images = convert_from_bytes(
                pdf_data,
                dpi=200,  # Good balance of quality and size
                fmt='jpeg',
            )
            
            # Convert each PIL Image to bytes
            image_bytes_list = []
            for image in images:
                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=self.JPEG_QUALITY)
                image_bytes_list.append(buffer.getvalue())
            
            logger.debug(f"Converted PDF to {len(image_bytes_list)} images")
            return image_bytes_list
            
        except Exception as e:
            raise OCRProcessingError(f"Failed to convert PDF to images: {e}")
    
    # =========================================================================
    # OCR Methods
    # =========================================================================
    
    async def extract_text(self, image_data: bytes) -> OCRResult:
        """Extract text from an image using chandra_ocr.
        
        Sends the image to LMStudio's vision model for text extraction.
        
        Args:
            image_data: Raw image bytes (PNG, JPG, JPEG supported)
            
        Returns:
            OCRResult with extracted text
            
        Raises:
            OCRConnectionError: If LMStudio is unavailable
            OCRProcessingError: If text extraction fails
        """
        try:
            # Prepare image
            base64_image = self._prepare_image(image_data)
            
            # Build request payload for OpenAI-compatible vision API
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract all text from this image. Return only the extracted text, preserving the original layout and formatting as much as possible. Do not add any explanations or commentary."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 4096,
                "temperature": 0.1,  # Low temperature for more deterministic output
            }
            
            # Send request to LMStudio
            client = await self._get_client()
            response = await client.post(
                f"{self.lmstudio_url}/chat/completions",
                json=payload,
            )
            
            # Handle errors
            if response.status_code == 404:
                raise OCRModelNotFoundError(
                    f"Model '{self.model_name}' not found. "
                    "Please ensure the chandra_ocr model is loaded in LMStudio."
                )
            elif response.status_code != 200:
                error_text = response.text
                raise OCRProcessingError(
                    f"LMStudio returned error {response.status_code}: {error_text}"
                )
            
            # Parse response
            data = response.json()
            choices = data.get("choices", [])
            
            if not choices:
                return OCRResult(
                    text="",
                    error="No response from OCR model",
                )
            
            # Extract text from response
            message = choices[0].get("message", {})
            extracted_text = message.get("content", "")
            
            # Normalize text (full-width to half-width conversion)
            normalized_text = self.normalize_text(extracted_text)
            
            return OCRResult(
                text=normalized_text,
                pages=1,
                page_texts=[normalized_text],
            )
            
        except httpx.ConnectError as e:
            raise OCRConnectionError(
                f"Cannot connect to LMStudio at {self.lmstudio_url}. "
                f"Please ensure LMStudio is running and the chandra_ocr model is loaded. "
                f"Error: {e}"
            )
        except httpx.TimeoutException as e:
            raise OCRConnectionError(
                f"Request to LMStudio timed out after {self.timeout}s. "
                f"The image may be too large or the model may be slow. "
                f"Error: {e}"
            )
        except (OCRConnectionError, OCRProcessingError, OCRModelNotFoundError):
            raise
        except Exception as e:
            raise OCRProcessingError(f"OCR extraction failed: {e}")
    
    async def extract_from_pdf(self, pdf_data: bytes) -> OCRResult:
        """Extract text from a PDF document.
        
        Converts each PDF page to an image and processes with OCR.
        Results from all pages are combined.
        
        Args:
            pdf_data: Raw PDF bytes
            
        Returns:
            OCRResult with combined text from all pages
            
        Raises:
            OCRConnectionError: If LMStudio is unavailable
            OCRProcessingError: If PDF conversion or text extraction fails
        """
        try:
            # Convert PDF to images
            page_images = self._convert_pdf_to_images(pdf_data)
            
            if not page_images:
                return OCRResult(
                    text="",
                    pages=0,
                    error="PDF contains no pages",
                )
            
            # Process each page
            page_texts: List[str] = []
            errors: List[str] = []
            
            for i, image_data in enumerate(page_images):
                try:
                    result = await self.extract_text(image_data)
                    if result.success:
                        page_texts.append(result.text)
                    else:
                        errors.append(f"Page {i + 1}: {result.error}")
                        page_texts.append("")  # Placeholder for failed page
                except Exception as e:
                    errors.append(f"Page {i + 1}: {str(e)}")
                    page_texts.append("")
            
            # Combine results
            combined_text = "\n\n--- Page Break ---\n\n".join(
                text for text in page_texts if text
            )
            
            # Determine overall success
            error_message = None
            if errors:
                if not combined_text:
                    error_message = "; ".join(errors)
                else:
                    # Partial success - log warnings but don't fail
                    for error in errors:
                        logger.warning(f"PDF OCR partial failure: {error}")
            
            return OCRResult(
                text=combined_text,
                pages=len(page_images),
                page_texts=page_texts,
                error=error_message,
            )
            
        except OCRProcessingError:
            raise
        except Exception as e:
            raise OCRProcessingError(f"PDF OCR extraction failed: {e}")
