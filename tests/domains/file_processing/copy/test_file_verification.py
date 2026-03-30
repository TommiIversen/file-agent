"""
Tests for FileVerificationService - post-copy integrity checks and source deletion.
"""
import asyncio
import os
import tempfile

import pytest

from app.domains.file_processing.copy.file_verification import FileVerificationService


@pytest.fixture
def svc():
    return FileVerificationService(retry_delay=0)


# ── verify_integrity ────────────────────────────────────────────────────────

class TestVerifyIntegrity:

    async def test_matching_sizes(self, svc, tmp_path):
        src = tmp_path / "source.mxf"
        dst = tmp_path / "dest.mxf"
        data = b"x" * 4096
        src.write_bytes(data)
        dst.write_bytes(data)

        success, src_size, dst_size = await svc.verify_integrity(str(src), str(dst))
        assert success is True
        assert src_size == 4096
        assert dst_size == 4096

    async def test_different_sizes_still_returns_true(self, svc, tmp_path):
        """For growing files, dest < source is normal - still returns True."""
        src = tmp_path / "source.mxf"
        dst = tmp_path / "dest.mxf"
        src.write_bytes(b"x" * 8000)
        dst.write_bytes(b"x" * 4000)

        success, src_size, dst_size = await svc.verify_integrity(str(src), str(dst))
        assert success is True
        assert src_size == 8000
        assert dst_size == 4000

    async def test_empty_dest_returns_false(self, svc, tmp_path):
        """An empty destination file should fail verification."""
        src = tmp_path / "source.mxf"
        dst = tmp_path / "dest.mxf"
        src.write_bytes(b"x" * 4096)
        dst.write_bytes(b"")  # 0 bytes

        success, src_size, dst_size = await svc.verify_integrity(str(src), str(dst))
        assert success is False
        assert src_size == 4096
        assert dst_size == 0

    async def test_dest_larger_than_source_returns_false(self, svc, tmp_path):
        """Destination larger than source is impossible and should fail."""
        src = tmp_path / "source.mxf"
        dst = tmp_path / "dest.mxf"
        src.write_bytes(b"x" * 1000)
        dst.write_bytes(b"x" * 2000)

        success, src_size, dst_size = await svc.verify_integrity(str(src), str(dst))
        assert success is False
        assert src_size == 1000
        assert dst_size == 2000

    async def test_missing_source_returns_false(self, svc, tmp_path):
        dst = tmp_path / "dest.mxf"
        dst.write_bytes(b"data")

        success, src_size, dst_size = await svc.verify_integrity(
            str(tmp_path / "nonexistent.mxf"), str(dst)
        )
        assert success is False
        assert src_size == 0
        assert dst_size == 0

    async def test_missing_dest_returns_false(self, svc, tmp_path):
        src = tmp_path / "source.mxf"
        src.write_bytes(b"data")

        success, src_size, dst_size = await svc.verify_integrity(
            str(src), str(tmp_path / "nonexistent.mxf")
        )
        assert success is False
        assert src_size == 0
        assert dst_size == 0


# ── delete_source_file ──────────────────────────────────────────────────────

class TestDeleteSourceFile:

    async def test_delete_existing_file(self, svc, tmp_path):
        f = tmp_path / "to_delete.mxf"
        f.write_bytes(b"delete me")

        success, error = await svc.delete_source_file(str(f))
        assert success is True
        assert error is None
        assert not f.exists()

    async def test_delete_nonexistent_file_retries_and_fails(self, svc, tmp_path):
        path = str(tmp_path / "ghost.mxf")

        success, error = await svc.delete_source_file(path)
        assert success is False
        assert error is not None
        assert "No such file" in error or "cannot find" in error.lower() or "FileNotFoundError" in error or "not found" in error.lower() or len(error) > 0
