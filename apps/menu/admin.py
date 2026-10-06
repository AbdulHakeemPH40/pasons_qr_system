from django.contrib import admin

from .models import MenuCategory, MenuItem


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_ar", "brand", "outlet", "sort_order", "active")
    list_filter = ("brand", "active")
    search_fields = ("name_en", "name_ar")


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        "name_en", "brand", "outlet", "category", "regular_price",
        "offer_price", "currency", "dietary_type", "available", "featured",
    )
    list_filter = ("brand", "category", "dietary_type", "available", "featured")
    search_fields = ("name_en", "name_ar")
    autocomplete_fields = ("category",)
