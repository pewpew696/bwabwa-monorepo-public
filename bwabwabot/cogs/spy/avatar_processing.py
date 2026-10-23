from PIL import Image, ImageOps

# === KONFIGURASI KOORDINAT & ROTASI ===
AVATAR_BOX = (75, 25, 305, 275)   # Ukuran baru yang diperbesar agar tidak bocor
AVATAR_ROTATION = 10              # Rotasi positif agar condong ke kiri searah polaroid

def process_avatar(avatar_img: Image.Image) -> Image.Image:
    """Memotong (crop) dan resize gambar avatar agar pas dengan ukuran kotak."""
    box_w = AVATAR_BOX[2] - AVATAR_BOX[0]
    box_h = AVATAR_BOX[3] - AVATAR_BOX[1]
    # ImageOps.fit otomatis melakukan resize dan crop yang proporsional
    return ImageOps.fit(avatar_img, (box_w, box_h), Image.LANCZOS)

def paste_avatar(template: Image.Image, avatar_img: Image.Image | None) -> Image.Image:
    """Proses avatar, lalu selipkan di BAWAH template yang sudah bolong.

    avatar_img boleh None (avatar gagal didownload) — dalam kasus itu,
    template dikembalikan apa adanya (kotak avatar dibiarkan kosong/bolong)
    supaya report tetap bisa dikirim tanpa avatar, bukan error."""
    if avatar_img is None:
        return template.convert("RGB")

    # 1. Proses avatar (fit ke box baru)
    processed = process_avatar(avatar_img)
    
    # 2. Putar dan WAJIB ubah ke RGBA agar tidak error saat format aslinya JPG
    rotated = processed.rotate(AVATAR_ROTATION, resample=Image.BICUBIC, expand=True).convert("RGBA")

    # 3. Hitung titik tengah pas di dalam bingkai
    box_w = AVATAR_BOX[2] - AVATAR_BOX[0]
    box_h = AVATAR_BOX[3] - AVATAR_BOX[1]
    cx = AVATAR_BOX[0] + box_w // 2
    cy = AVATAR_BOX[1] + box_h // 2
    paste_x = cx - rotated.width // 2
    paste_y = cy - rotated.height // 2

    # 4. Buat kanvas kosong seukuran template untuk menaruh avatar di paling bawah
    canvas = Image.new("RGBA", template.size, (0, 0, 0, 0))
    canvas.alpha_composite(rotated, (paste_x, paste_y))

    # 5. Tumpuk template map (spy_report.png) di atas avatar
    template_rgba = template.convert("RGBA")
    canvas.alpha_composite(template_rgba, (0, 0))
    
    return canvas.convert("RGB")
