from django import forms

from .models import Component, Product, Project


class NewProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name"]


class NewProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name"]


class NewComponentForm(forms.ModelForm):
    class Meta:
        model = Component
        fields = ["name"]
