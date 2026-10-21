"""
StudyBuddy - Teman pengingat digital untuk mengatur tugas dan jadwal belajar.

Fitur:
  - Tambah tugas (PR / Tugas / Belajar), catat deadline, tentukan prioritas
  - Atur jadwal belajar mingguan
  - Tandai tugas selesai dan lihat progress belajar
  - Login Admin di sidebar (password di-hash SHA-256)

Hak akses:
  - Pengguna biasa : melihat dan menginput data (tugas & jadwal)
  - Admin          : semua hak pengguna + ubah status selesai + hapus data

Jalankan secara lokal:
    pip install streamlit pandas
    streamlit run app.py

Akun admin awal (SEGERA GANTI lewat menu sidebar setelah login):
    username : admin
    password : admin123
"""

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------
# KONFIGURASI
# ----------------------------------------------------------------------------
DB_PATH = "studybuddy.db"
ZONA_WAKTU = timezone(timedelta(hours=8))  # WITA (UTC+8). Ubah ke 7 untuk WIB.
FORMAT_DT = "%Y-%m-%d %H:%M"

PRIORITAS = ["Tinggi", "Sedang", "Rendah"]
IKON_PRIORITAS = {"Tinggi": "🔴", "Sedang": "🟡", "Rendah": "🟢"}
KATEGORI = ["PR", "Tugas", "Belajar"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

ADMIN_AWAL_USER = "admin"
ADMIN_AWAL_PASS = "admin123"


# ----------------------------------------------------------------------------
# UTILITAS WAKTU
# ----------------------------------------------------------------------------
def sekarang() -> datetime:
    """Waktu saat ini (tanpa tzinfo) pada zona waktu yang dikonfigurasi."""
    return datetime.now(ZONA_WAKTU).replace(tzinfo=None)


# ----------------------------------------------------------------------------
# DATABASE
# ----------------------------------------------------------------------------
def koneksi() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def jalankan(query: str, params: tuple = ()) -> None:
    """Menjalankan perintah tulis (INSERT / UPDATE / DELETE)."""
    with closing(koneksi()) as conn:
        with conn:
            conn.execute(query, params)


def ambil_df(query: str, params: tuple = ()) -> pd.DataFrame:
    """Menjalankan perintah baca (SELECT) dan mengembalikan DataFrame."""
    with closing(koneksi()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def buat_hash(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash password dengan SHA-256 + salt acak. Mengembalikan (salt, hash)."""
    salt = salt or secrets.token_hex(16)
    hasil = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return salt, hasil


def inisialisasi_db() -> None:
    """Membuat tabel jika belum ada dan menyiapkan akun admin awal."""
    with closing(koneksi()) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pengguna (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tugas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    judul TEXT NOT NULL,
                    kategori TEXT NOT NULL,
                    deadline TEXT NOT NULL,
                    prioritas TEXT NOT NULL,
                    catatan TEXT DEFAULT '',
                    selesai INTEGER NOT NULL DEFAULT 0,
                    dibuat TEXT NOT NULL,
                    selesai_pada TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jadwal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hari TEXT NOT NULL,
                    jam_mulai TEXT NOT NULL,
                    jam_selesai TEXT NOT NULL,
                    kegiatan TEXT NOT NULL
                )
                """
            )
            ada = conn.execute("SELECT COUNT(*) FROM pengguna").fetchone()[0]
            if ada == 0:
                salt, hasil = buat_hash(ADMIN_AWAL_PASS)
                conn.execute(
                    "INSERT INTO pengguna (username, salt, password_hash) VALUES (?, ?, ?)",
                    (ADMIN_AWAL_USER, salt, hasil),
                )


# ----------------------------------------------------------------------------
# AUTENTIKASI
# ----------------------------------------------------------------------------
def verifikasi_login(username: str, password: str) -> bool:
    df = ambil_df(
        "SELECT salt, password_hash FROM pengguna WHERE username = ?", (username,)
    )
    if df.empty:
        return False
    _, hasil = buat_hash(password, df.loc[0, "salt"])
    return hmac.compare_digest(hasil, df.loc[0, "password_hash"])


def ganti_password(username: str, password_baru: str) -> None:
    salt, hasil = buat_hash(password_baru)
    jalankan(
        "UPDATE pengguna SET salt = ?, password_hash = ? WHERE username = ?",
        (salt, hasil, username),
    )


def admin_aktif() -> str | None:
    return st.session_state.get("admin_user")


# ----------------------------------------------------------------------------
# LOGIKA TUGAS
# ----------------------------------------------------------------------------
def tambah_tugas(
    judul: str, kategori: str, deadline: datetime, prioritas: str, catatan: str
) -> None:
    jalankan(
        """
        INSERT INTO tugas (judul, kategori, deadline, prioritas, catatan, dibuat)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            judul,
            kategori,
            deadline.strftime(FORMAT_DT),
            prioritas,
            catatan,
            sekarang().strftime(FORMAT_DT),
        ),
    )


def ambil_tugas() -> pd.DataFrame:
    """Belum selesai di atas, lalu urut prioritas (Tinggi dulu), lalu deadline."""
    return ambil_df(
        """
        SELECT * FROM tugas
        ORDER BY selesai ASC,
                 CASE prioritas WHEN 'Tinggi' THEN 1 WHEN 'Sedang' THEN 2 ELSE 3 END,
                 deadline ASC
        """
    )


def ubah_status_tugas(id_tugas: int, selesai: bool) -> None:
    waktu = sekarang().strftime(FORMAT_DT) if selesai else None
    jalankan(
        "UPDATE tugas SET selesai = ?, selesai_pada = ? WHERE id = ?",
        (1 if selesai else 0, waktu, id_tugas),
    )


def hapus_tugas(id_tugas: int) -> None:
    jalankan("DELETE FROM tugas WHERE id = ?", (id_tugas,))


def label_deadline(deadline_str: str, selesai: bool) -> str:
    if selesai:
        return "✅ Selesai"
    dl = datetime.strptime(deadline_str, FORMAT_DT)
    sekarang_ = sekarang()
    if dl < sekarang_:
        return "⛔ Terlambat"
    selisih_hari = (dl.date() - sekarang_.date()).days
    if selisih_hari == 0:
        return "⏰ Hari ini"
    return f"🗓️ H-{selisih_hari}"


def hitung_progress(df: pd.DataFrame) -> tuple[int, int, float]:
    total = len(df)
    selesai = int(df["selesai"].sum()) if total else 0
    persen = (selesai / total * 100) if total else 0.0
    return total, selesai, persen


def tugas_mendesak(df: pd.DataFrame) -> pd.DataFrame:
    """Tugas belum selesai yang terlambat atau jatuh tempo dalam 48 jam."""
    if df.empty:
        return df
    belum = df[df["selesai"] == 0].copy()
    if belum.empty:
        return belum
    belum["dl"] = pd.to_datetime(belum["deadline"], format=FORMAT_DT)
    batas = sekarang() + timedelta(hours=48)
    return belum[belum["dl"] <= batas].sort_values("dl")


# ----------------------------------------------------------------------------
# LOGIKA JADWAL
# ----------------------------------------------------------------------------
def tambah_jadwal(hari: str, mulai: time, selesai: time, kegiatan: str) -> None:
    jalankan(
        "INSERT INTO jadwal (hari, jam_mulai, jam_selesai, kegiatan) VALUES (?, ?, ?, ?)",
        (hari, mulai.strftime("%H:%M"), selesai.strftime("%H:%M"), kegiatan),
    )


def ambil_jadwal() -> pd.DataFrame:
    urutan = " ".join(f"WHEN '{h}' THEN {i}" for i, h in enumerate(HARI))
    return ambil_df(
        f"SELECT * FROM jadwal ORDER BY CASE hari {urutan} ELSE 99 END, jam_mulai ASC"
    )


def hapus_jadwal(id_jadwal: int) -> None:
    jalankan("DELETE FROM jadwal WHERE id = ?", (id_jadwal,))


# ----------------------------------------------------------------------------
# SIDEBAR: MENU & LOGIN ADMIN
# ----------------------------------------------------------------------------
def sidebar() -> str:
    st.sidebar.title("🎓 StudyBuddy")
    st.sidebar.caption("Teman pengingat digital untuk tugas & jadwal belajar")

    menu = st.sidebar.radio(
        "Menu",
        ["🏠 Dashboard", "➕ Tambah Tugas", "📋 Daftar Tugas", "🗓️ Jadwal Belajar", "📈 Progress"],
    )

    st.sidebar.divider()
    st.sidebar.subheader("🔐 Login Admin")

    admin = admin_aktif()
    if admin:
        st.sidebar.success(f"Masuk sebagai **{admin}**")
        if st.sidebar.button("Keluar", use_container_width=True):
            st.session_state.pop("admin_user", None)
            st.rerun()

        with st.sidebar.expander("Ganti password"):
            with st.form("form_ganti_password", clear_on_submit=True):
                lama = st.text_input("Password lama", type="password")
                baru = st.text_input("Password baru (min. 6 karakter)", type="password")
                ulang = st.text_input("Ulangi password baru", type="password")
                kirim = st.form_submit_button("Simpan password")
            if kirim:
                if not verifikasi_login(admin, lama):
                    st.error("Password lama salah.")
                elif len(baru) < 6:
                    st.error("Password baru minimal 6 karakter.")
                elif baru != ulang:
                    st.error("Konfirmasi password tidak sama.")
                else:
                    ganti_password(admin, baru)
                    st.success("Password berhasil diganti.")
    else:
        with st.sidebar.form("form_login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            masuk = st.form_submit_button("Masuk", use_container_width=True)
        if masuk:
            if verifikasi_login(username.strip(), password):
                st.session_state["admin_user"] = username.strip()
                st.rerun()
            else:
                st.sidebar.error("Username atau password salah.")
        st.sidebar.caption(
            "Pengguna biasa dapat melihat dan menambah data. "
            "Login admin untuk mengubah status atau menghapus data."
        )
    return menu


# ----------------------------------------------------------------------------
# HALAMAN
# ----------------------------------------------------------------------------
def halaman_dashboard() -> None:
    st.title("🏠 Dashboard")
    df = ambil_tugas()
    total, selesai, persen = hitung_progress(df)
    belum = total - selesai
    terlambat = 0
    if not df.empty:
        terlambat = sum(
            1
            for _, r in df.iterrows()
            if r["selesai"] == 0
            and datetime.strptime(r["deadline"], FORMAT_DT) < sekarang()
        )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total tugas", total)
    k2.metric("Selesai", selesai)
    k3.metric("Belum selesai", belum)
    k4.metric("Terlambat", terlambat)

    st.subheader("Progress belajar")
    st.progress(persen / 100, text=f"{persen:.0f}% tugas selesai")

    st.subheader("⏰ Pengingat deadline")
    mendesak = tugas_mendesak(df)
    if mendesak.empty:
        st.success("Tidak ada tugas yang mendesak. Tetap semangat! 🎉")
    else:
        for _, r in mendesak.iterrows():
            teks = (
                f"{IKON_PRIORITAS[r['prioritas']]} **{r['judul']}** ({r['kategori']}) - "
                f"deadline {r['deadline']} - {label_deadline(r['deadline'], False)}"
            )
            if r["dl"] < sekarang():
                st.error(teks)
            else:
                st.warning(teks)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Tugas prioritas teratas")
        belum_df = df[df["selesai"] == 0].head(5) if not df.empty else df
        if belum_df.empty:
            st.info("Belum ada tugas aktif.")
        else:
            for _, r in belum_df.iterrows():
                st.write(
                    f"{IKON_PRIORITAS[r['prioritas']]} **{r['judul']}** - {r['deadline']}"
                )
    with col_b:
        hari_ini = HARI[sekarang().weekday()]
        st.subheader(f"Jadwal hari ini ({hari_ini})")
        jadwal = ambil_jadwal()
        jadwal = jadwal[jadwal["hari"] == hari_ini] if not jadwal.empty else jadwal
        if jadwal.empty:
            st.info("Tidak ada jadwal belajar hari ini.")
        else:
            for _, r in jadwal.iterrows():
                st.write(f"🕒 {r['jam_mulai']} - {r['jam_selesai']}  |  {r['kegiatan']}")


def halaman_tambah_tugas() -> None:
    st.title("➕ Tambah Tugas")
    with st.form("form_tugas", clear_on_submit=True):
        judul = st.text_input("Judul tugas", placeholder="Contoh: PR Matematika Bab 3")
        c1, c2 = st.columns(2)
        kategori = c1.selectbox("Kategori", KATEGORI)
        prioritas = c2.selectbox("Prioritas", PRIORITAS, index=1)
        c3, c4 = st.columns(2)
        tanggal = c3.date_input("Tanggal deadline", value=sekarang().date() + timedelta(days=1))
        jam = c4.time_input("Jam deadline", value=time(23, 59))
        catatan = st.text_area("Catatan (opsional)")
        simpan = st.form_submit_button("Simpan tugas", use_container_width=True)

    if simpan:
        if not judul.strip():
            st.error("Judul tugas tidak boleh kosong.")
            return
        deadline = datetime.combine(tanggal, jam)
        tambah_tugas(judul.strip(), kategori, deadline, prioritas, catatan.strip())
        st.success(f"Tugas '{judul.strip()}' berhasil ditambahkan.")
        if deadline < sekarang():
            st.warning("Perhatian: deadline yang Anda pilih sudah lewat.")


def halaman_daftar_tugas() -> None:
    st.title("📋 Daftar Tugas")
    admin = admin_aktif()
    if not admin:
        st.info("Anda masuk sebagai pengguna biasa. Login admin untuk menandai selesai atau menghapus tugas.")

    df = ambil_tugas()
    if df.empty:
        st.info("Belum ada tugas. Tambahkan lewat menu 'Tambah Tugas'.")
        return

    f1, f2, f3 = st.columns(3)
    status = f1.selectbox("Status", ["Semua", "Belum selesai", "Selesai"])
    pilih_prioritas = f2.multiselect("Prioritas", PRIORITAS, default=PRIORITAS)
    pilih_kategori = f3.multiselect("Kategori", KATEGORI, default=KATEGORI)

    if status == "Belum selesai":
        df = df[df["selesai"] == 0]
    elif status == "Selesai":
        df = df[df["selesai"] == 1]
    df = df[df["prioritas"].isin(pilih_prioritas) & df["kategori"].isin(pilih_kategori)]

    if df.empty:
        st.warning("Tidak ada tugas yang cocok dengan filter.")
        return

    for _, r in df.iterrows():
        id_tugas = int(r["id"])
        selesai = bool(r["selesai"])
        with st.container(border=True):
            kolom_info, kolom_aksi = st.columns([4, 2])
            with kolom_info:
                judul = f"~~{r['judul']}~~" if selesai else f"**{r['judul']}**"
                st.markdown(f"{IKON_PRIORITAS[r['prioritas']]} {judul}")
                st.caption(
                    f"{r['kategori']}  |  Prioritas {r['prioritas']}  |  "
                    f"Deadline {r['deadline']}  |  {label_deadline(r['deadline'], selesai)}"
                )
                if r["catatan"]:
                    st.write(r["catatan"])
            with kolom_aksi:
                if admin:
                    teks_tombol = "↩️ Batalkan selesai" if selesai else "✅ Tandai selesai"
                    if st.button(teks_tombol, key=f"status_{id_tugas}", use_container_width=True):
                        ubah_status_tugas(id_tugas, not selesai)
                        st.rerun()
                    if st.button("🗑️ Hapus", key=f"hapus_{id_tugas}", use_container_width=True):
                        hapus_tugas(id_tugas)
                        st.rerun()
                else:
                    st.caption("🔒 Khusus admin")


def halaman_jadwal() -> None:
    st.title("🗓️ Jadwal Belajar")
    admin = admin_aktif()

    with st.form("form_jadwal", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        hari = c1.selectbox("Hari", HARI, index=sekarang().weekday())
        mulai = c2.time_input("Jam mulai", value=time(16, 0))
        selesai = c3.time_input("Jam selesai", value=time(17, 0))
        kegiatan = st.text_input("Kegiatan belajar", placeholder="Contoh: Belajar Fisika")
        simpan = st.form_submit_button("Tambah ke jadwal", use_container_width=True)

    if simpan:
        if not kegiatan.strip():
            st.error("Kegiatan tidak boleh kosong.")
        elif selesai <= mulai:
            st.error("Jam selesai harus lebih besar dari jam mulai.")
        else:
            tambah_jadwal(hari, mulai, selesai, kegiatan.strip())
            st.success("Jadwal berhasil ditambahkan.")

    st.subheader("Jadwal mingguan")
    jadwal = ambil_jadwal()
    if jadwal.empty:
        st.info("Belum ada jadwal belajar.")
        return

    for hari_nama in HARI:
        bagian = jadwal[jadwal["hari"] == hari_nama]
        if bagian.empty:
            continue
        st.markdown(f"**{hari_nama}**")
        for _, r in bagian.iterrows():
            k1, k2 = st.columns([5, 1])
            k1.write(f"🕒 {r['jam_mulai']} - {r['jam_selesai']}  |  {r['kegiatan']}")
            if admin:
                if k2.button("🗑️", key=f"hapus_jadwal_{int(r['id'])}"):
                    hapus_jadwal(int(r["id"]))
                    st.rerun()
    if not admin:
        st.caption("🔒 Login admin untuk menghapus jadwal.")


def halaman_progress() -> None:
    st.title("📈 Progress Belajar")
    df = ambil_tugas()
    if df.empty:
        st.info("Belum ada data tugas untuk dihitung.")
        return

    total, selesai, persen = hitung_progress(df)
    st.progress(persen / 100, text=f"{persen:.0f}% tugas selesai ({selesai} dari {total})")

    st.subheader("Progress per prioritas")
    per_prioritas = (
        df.groupby("prioritas")
        .agg(Total=("id", "count"), Selesai=("selesai", "sum"))
        .reindex(PRIORITAS)
        .fillna(0)
        .astype(int)
    )
    per_prioritas["Persen (%)"] = (per_prioritas["Selesai"] / per_prioritas["Total"].replace(0, 1) * 100).round(0)
    st.dataframe(per_prioritas, use_container_width=True)

    st.subheader("Progress per kategori")
    per_kategori = (
        df.groupby("kategori")
        .agg(Total=("id", "count"), Selesai=("selesai", "sum"))
        .astype(int)
    )
    per_kategori["Persen (%)"] = (per_kategori["Selesai"] / per_kategori["Total"] * 100).round(0)
    st.bar_chart(per_kategori["Persen (%)"])

    st.subheader("Tugas selesai 7 hari terakhir")
    selesai_df = df[(df["selesai"] == 1) & df["selesai_pada"].notna()]
    hitung = selesai_df["selesai_pada"].str[:10].value_counts()
    hari_list: list[date] = [sekarang().date() - timedelta(days=i) for i in range(6, -1, -1)]
    data = pd.DataFrame(
        {"Tugas selesai": [int(hitung.get(h.isoformat(), 0)) for h in hari_list]},
        index=[h.strftime("%d %b") for h in hari_list],
    )
    st.bar_chart(data)


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="StudyBuddy", page_icon="🎓", layout="wide")
    inisialisasi_db()
    menu = sidebar()

    if menu == "🏠 Dashboard":
        halaman_dashboard()
    elif menu == "➕ Tambah Tugas":
        halaman_tambah_tugas()
    elif menu == "📋 Daftar Tugas":
        halaman_daftar_tugas()
    elif menu == "🗓️ Jadwal Belajar":
        halaman_jadwal()
    else:
        halaman_progress()


if __name__ == "__main__":
    main()
