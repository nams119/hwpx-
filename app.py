"""
HWPX 이미지 도구 - Streamlit 웹 앱
기능 1: HWPX 내 이미지 압축 후 다운로드
기능 2: HWPX 내 이미지 전체 추출 후 ZIP 다운로드
"""

import streamlit as st
import os
import zipfile
import shutil
import io
import base64
import uuid
from pathlib import Path
from PIL import Image
import xml.etree.ElementTree as ET

# ──────────────────────────────────────────
# 핵심 압축 로직
# ──────────────────────────────────────────

class HWPXProcessor:
    def __init__(self, target_size_kb=200):
        self.target_size_kb = target_size_kb
        self.target_size_bytes = target_size_kb * 1024

    def compress_image(self, image_data):
        """이미지를 목표 크기 이하로 압축"""
        try:
            img = Image.open(io.BytesIO(image_data))
        except Exception:
            return image_data

        # 색상 모드 정규화
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 품질 조정
        for quality in range(95, 4, -5):
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            if output.tell() <= self.target_size_bytes:
                return output.getvalue()

        # 크기 조정
        scale = 0.9
        while scale > 0.3:
            resized = img.resize(
                (int(img.width * scale), int(img.height * scale)),
                Image.Resampling.LANCZOS
            )
            output = io.BytesIO()
            resized.save(output, format='JPEG', quality=85, optimize=True)
            if output.tell() <= self.target_size_bytes:
                return output.getvalue()
            scale -= 0.1

        output = io.BytesIO()
        resized.save(output, format='JPEG', quality=60, optimize=True)
        return output.getvalue()

    def compress_hwpx(self, hwpx_bytes, progress_bar=None):
        """HWPX 바이트 데이터를 받아 압축 후 반환"""
        work_dir = f"/tmp/hwpx_{uuid.uuid4().hex}"
        os.makedirs(work_dir, exist_ok=True)

        stats = {"compressed": 0, "skipped": 0, "original_total": 0, "compressed_total": 0}

        try:
            # 압축 해제
            with zipfile.ZipFile(io.BytesIO(hwpx_bytes), 'r') as zf:
                zf.extractall(work_dir)

            # BinData 이미지 처리
            bindata_path = os.path.join(work_dir, 'BinData')
            image_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')

            if os.path.exists(bindata_path):
                image_files = [f for f in os.listdir(bindata_path)
                               if f.lower().endswith(image_exts)]
                total = len(image_files)

                for idx, fname in enumerate(image_files):
                    fpath = os.path.join(bindata_path, fname)
                    with open(fpath, 'rb') as f:
                        data = f.read()

                    orig_size = len(data)
                    stats["original_total"] += orig_size

                    if progress_bar:
                        progress_bar.progress(int((idx + 1) / max(total, 1) * 85),
                                              text=f"압축 중... ({idx+1}/{total})")

                    if orig_size <= self.target_size_bytes:
                        stats["skipped"] += 1
                        stats["compressed_total"] += orig_size
                        continue

                    compressed = self.compress_image(data)
                    with open(fpath, 'wb') as f:
                        f.write(compressed)
                    stats["compressed"] += 1
                    stats["compressed_total"] += len(compressed)

            # 다시 HWPX로 묶기
            if progress_bar:
                progress_bar.progress(95, text="HWPX 파일 생성 중...")

            output_buf = io.BytesIO()
            with zipfile.ZipFile(output_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(work_dir):
                    for file in files:
                        fp = os.path.join(root, file)
                        zf.write(fp, os.path.relpath(fp, work_dir))

            if progress_bar:
                progress_bar.progress(100, text="완료!")

            return output_buf.getvalue(), stats

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def extract_images(self, hwpx_bytes, progress_bar=None):
        """HWPX 내 이미지를 모두 추출하여 ZIP 바이트로 반환"""
        work_dir = f"/tmp/hwpx_{uuid.uuid4().hex}"
        os.makedirs(work_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(io.BytesIO(hwpx_bytes), 'r') as zf:
                zf.extractall(work_dir)

            bindata_path = os.path.join(work_dir, 'BinData')
            image_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff')

            if not os.path.exists(bindata_path):
                return None, 0

            image_files = [f for f in os.listdir(bindata_path)
                           if f.lower().endswith(image_exts)]

            if not image_files:
                return None, 0

            total = len(image_files)
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, fname in enumerate(image_files):
                    if progress_bar:
                        progress_bar.progress(int((idx + 1) / total * 100),
                                              text=f"추출 중... ({idx+1}/{total})")
                    fpath = os.path.join(bindata_path, fname)
                    zf.write(fpath, fname)

            return zip_buf.getvalue(), total

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


# ──────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────

def format_size(size_bytes):
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    return f"{size_bytes / 1024:.1f} KB"


def main():
    st.set_page_config(
        page_title="HWPX 이미지 도구",
        page_icon="📄",
        layout="centered"
    )

    st.title("📄 HWPX 이미지 도구")
    st.caption("한글(HWPX) 파일의 이미지를 압축하거나 추출합니다.")

    # 탭 구성
    tab1, tab2 = st.tabs(["🗜️ 이미지 압축", "📦 이미지 추출"])

    # ── 탭1: 이미지 압축 ──────────────────────
    with tab1:
        st.subheader("이미지 압축 후 HWPX 다운로드")
        st.info("업로드한 HWPX 파일의 이미지를 일괄 압축하여 용량을 줄입니다.")

        uploaded = st.file_uploader(
            "HWPX 파일 선택", type=["hwpx", "hwp"], key="compress_upload"
        )

        size_option = st.radio(
            "이미지당 목표 압축 크기",
            options=[50, 100, 200, 500, 1000],
            format_func=lambda x: {
                50: "매우 작게 (50KB)",
                100: "작게 (100KB)",
                200: "중간 (200KB) - 권장",
                500: "크게 (500KB)",
                1000: "아주 크게 (1MB)"
            }[x],
            index=2,
            horizontal=True,
            key="size_radio"
        )

        if uploaded and uploaded.name.lower().endswith('.hwp') and not uploaded.name.lower().endswith('.hwpx'):
            st.error(
                "⚠️ HWP 파일은 지원하지 않습니다.\n\n"
                "**HWPX 파일로 변환 후 업로드해 주세요.**\n\n"
                "한컴오피스에서: `파일` → `다른 이름으로 저장` → 파일 형식을 **HWPX**로 선택 후 저장"
            )

        if uploaded and uploaded.name.lower().endswith('.hwpx') and st.button("🗜️ 압축 시작", type="primary", key="compress_btn"):
            hwpx_bytes = uploaded.read()
            original_size = len(hwpx_bytes)

            st.write(f"**원본 크기:** {format_size(original_size)}")

            progress = st.progress(0, text="준비 중...")
            processor = HWPXProcessor(target_size_kb=size_option)

            with st.spinner("압축 처리 중..."):
                result_bytes, stats = processor.compress_hwpx(hwpx_bytes, progress_bar=progress)

            compressed_size = len(result_bytes)
            reduction = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0

            st.success("✅ 압축 완료!")

            col1, col2, col3 = st.columns(3)
            col1.metric("압축된 이미지", f"{stats['compressed']}개")
            col2.metric("스킵 (이미 작음)", f"{stats['skipped']}개")
            col3.metric("용량 감소", f"{reduction:.1f}%")

            col4, col5 = st.columns(2)
            col4.metric("원본 크기", format_size(original_size))
            col5.metric("압축 후 크기", format_size(compressed_size))

            out_name = Path(uploaded.name).stem + "_compressed.hwpx"
            st.download_button(
                label="⬇️ 압축된 HWPX 다운로드",
                data=result_bytes,
                file_name=out_name,
                mime="application/octet-stream",
                type="primary"
            )

    # ── 탭2: 이미지 추출 ──────────────────────
    with tab2:
        st.subheader("HWPX 내 이미지 전체 추출")
        st.info("업로드한 HWPX 파일에서 이미지를 모두 꺼내 ZIP 파일로 다운로드합니다.")

        uploaded2 = st.file_uploader(
            "HWPX 파일 선택", type=["hwpx", "hwp"], key="extract_upload"
        )

        if uploaded2 and uploaded2.name.lower().endswith('.hwp') and not uploaded2.name.lower().endswith('.hwpx'):
            st.error(
                "⚠️ HWP 파일은 지원하지 않습니다.\n\n"
                "**HWPX 파일로 변환 후 업로드해 주세요.**\n\n"
                "한컴오피스에서: `파일` → `다른 이름으로 저장` → 파일 형식을 **HWPX**로 선택 후 저장"
            )

        if uploaded2 and uploaded2.name.lower().endswith('.hwpx') and st.button("📦 이미지 추출 시작", type="primary", key="extract_btn"):
            hwpx_bytes = uploaded2.read()

            progress2 = st.progress(0, text="준비 중...")
            processor2 = HWPXProcessor()

            with st.spinner("이미지 추출 중..."):
                zip_bytes, count = processor2.extract_images(hwpx_bytes, progress_bar=progress2)

            if zip_bytes is None or count == 0:
                st.warning("⚠️ 추출할 이미지가 없습니다.")
            else:
                st.success(f"✅ 이미지 {count}개 추출 완료!")

                out_zip_name = Path(uploaded2.name).stem + "_images.zip"
                st.download_button(
                    label=f"⬇️ 이미지 ZIP 다운로드 ({count}개)",
                    data=zip_bytes,
                    file_name=out_zip_name,
                    mime="application/zip",
                    type="primary"
                )

    st.divider()
    st.caption("⚠️ HWP 파일은 지원하지 않습니다. HWPX 파일로 업로드해 주세요.")
    st.caption("⚠️ 민감한 정보가 담긴 문서는 업로드하지 마세요.")
    st.caption("⚠️ 중요한 문서는 반드시 원본 백업 후 사용하세요.")
    st.caption("⚠️ 200MB 이상 파일은 업로드가 되지 않을 수 있습니다.")


if __name__ == "__main__":
    main()
