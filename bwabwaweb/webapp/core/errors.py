"""Hierarki error aplikasi. Pesan ke client selalu dari public_message."""


class AppError(Exception):
    status_code = 500
    public_message = "Terjadi kesalahan pada server."

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.public_message)
        self.detail = detail


class ValidationAppError(AppError):
    status_code = 422
    public_message = "Input tidak valid."


class UnauthorizedError(AppError):
    status_code = 401
    public_message = "Sesi tidak valid. Silakan masuk."


class ForbiddenError(AppError):
    status_code = 403
    public_message = "Akses ditolak."


class NotFoundError(AppError):
    status_code = 404
    public_message = "Data tidak ditemukan."


class ConflictError(AppError):
    status_code = 409
    public_message = "Permintaan bertentangan dengan kondisi saat ini."


class RateLimitedError(AppError):
    status_code = 429
    public_message = "Terlalu banyak permintaan. Coba lagi sebentar."


class InvalidPasswordError(UnauthorizedError):
    public_message = "Password salah."


class TierRequiredError(ForbiddenError):
    public_message = "Fitur ini memerlukan password upgrade."

    def __init__(self, required_tier: str) -> None:
        super().__init__(f"butuh tier {required_tier}")
        self.required_tier = required_tier
