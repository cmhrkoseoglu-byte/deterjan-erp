from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Varsayılan sayfalama: 50 kayıt; `?page=2&page_size=100` (en fazla 500)."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
