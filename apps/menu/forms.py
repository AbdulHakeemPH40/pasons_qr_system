"""
Panel forms for the menu app.

SpecialItemForm powers both "Add special" and "Edit special" in the staff
panel. Staff (head office or outlet manager) update promo cards dynamically:
name, description, photo upload, optional price / offer, badge label, order
and live status. Validation lives here so every entry point behaves the same.
"""

from django import forms

from apps.menu.models import SpecialItem


class SpecialItemForm(forms.ModelForm):
    """
    Create/update one promo card.

    Rules enforced here (mirrored on the customer page):
    - Weekend specials never carry a price: any entered price is dropped.
    - Offers need an original price to strike through when an offer price
      or discount label is given.
    - The photo is optional; cards without one fall back to branded art.
    """

    image_clear = forms.BooleanField(
        required=False,
        label="Remove current photo",
        help_text="Tick to delete the uploaded photo and use the branded fallback art.",
    )

    class Meta:
        model = SpecialItem
        fields = [
            "brand", "outlet", "kind", "title_en", "title_ar", "description",
            "image", "original_price", "offer_price", "discount_label",
            "display_order", "active",
        ]
        widgets = {
            "title_en": forms.TextInput(attrs={"maxlength": 140}),
            "title_ar": forms.TextInput(attrs={"dir": "rtl", "maxlength": 140}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "discount_label": forms.TextInput(attrs={"placeholder": "e.g. 22% OFF or Free delivery"}),
            "display_order": forms.NumberInput(attrs={"min": 0}),
        }

    def __init__(self, *args, brands, outlets, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["brand"].queryset = brands
        self.fields["outlet"].queryset = outlets
        self.fields["outlet"].required = False
        self.fields["outlet"].empty_label = "Whole brand"
        self.fields["original_price"].required = False
        self.fields["offer_price"].required = False
        self.fields["image"].required = False
        self.fields["display_order"].required = False

    def clean_display_order(self):
        value = self.cleaned_data.get("display_order")
        return 0 if value is None else value

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        if kind == SpecialItem.Kind.WEEKEND:
            # Weekend cards are photo + title only on the customer page.
            cleaned["original_price"] = None
            cleaned["offer_price"] = None
            cleaned["discount_label"] = ""
            return cleaned
        offer = cleaned.get("offer_price")
        original = cleaned.get("original_price")
        label = (cleaned.get("discount_label") or "").strip()
        if (offer or label) and not original:
            self.add_error(
                "original_price",
                "Set the original price so the offer can be struck through.",
            )
        if offer and original and offer >= original:
            self.add_error("offer_price", "The offer price must be lower than the original price.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("image_clear") and not self.cleaned_data.get("image"):
            if instance.image:
                instance.image.delete(save=False)
            instance.image = None
        if commit:
            instance.save()
        return instance
