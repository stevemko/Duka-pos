from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination that lets busy lists request a larger page."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
