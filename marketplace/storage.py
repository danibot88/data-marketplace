from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateFileStorage(FileSystemStorage):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("location", settings.PRIVATE_DATA_ROOT)
        kwargs.setdefault("base_url", None)
        super().__init__(*args, **kwargs)

    def url(self, name):
        raise ValueError("Arquivos privados não possuem URL pública.")


private_storage = PrivateFileStorage()
