from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.fields import empty

from .models import Branch, StaffProfile

User = get_user_model()


class BranchSerializer(serializers.ModelSerializer):
    staff_count = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = ["id", "name", "code", "address", "phone", "is_active", "staff_count", "created_at"]
        read_only_fields = ["created_at"]

    def get_staff_count(self, branch):
        return branch.staff.count()

    def validate_code(self, code):
        code = code.strip().upper()
        queryset = Branch.objects.filter(code__iexact=code)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Another branch already uses this code.")
        return code


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "first_name", "last_name", "email",
            "role", "branch", "phone", "is_active", "is_superuser",
            "date_joined", "last_login",
        ]
        read_only_fields = ["is_superuser", "last_login", "date_joined"]

    def get_full_name(self, user):
        return user.get_full_name() or user.get_username()

    def get_role(self, user):
        return "manager" if user.is_staff else "cashier"

    def get_branch(self, user):
        profile = getattr(user, "profile", None)
        if not profile or not profile.branch:
            return None
        return {
            "id": str(profile.branch_id),
            "name": profile.branch.name,
            "code": profile.branch.code,
        }

    def get_phone(self, user):
        profile = getattr(user, "profile", None)
        return profile.phone if profile else ""


class UserWriteSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=["cashier", "manager"], required=False)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True
    )
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "username", "first_name", "last_name", "email",
            "role", "branch", "phone", "is_active", "password",
        ]

    def validate_username(self, username):
        username = username.strip()
        queryset = User.objects.filter(username__iexact=username)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("That username is already taken.")
        return username

    def validate_password(self, password):
        try:
            validate_password(password)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return password

    def create(self, validated_data):
        branch = validated_data.pop("branch", None)
        phone = validated_data.pop("phone", "")
        password = validated_data.pop("password", None)
        role = validated_data.pop("role", "cashier")
        if not password:
            raise serializers.ValidationError({"password": "Set a password for this account."})

        user = User(**validated_data)
        user.is_staff = role == "manager"
        user.set_password(password)
        user.save()
        StaffProfile.objects.create(user=user, branch=branch, phone=phone)
        return user

    def update(self, instance, validated_data):
        branch = validated_data.pop("branch", empty)
        phone = validated_data.pop("phone", empty)
        role = validated_data.pop("role", None)
        validated_data.pop("password", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        if role is not None:
            instance.is_staff = role == "manager"
        instance.save()

        profile, _ = StaffProfile.objects.get_or_create(user=instance)
        if branch is not empty:
            profile.branch = branch
        if phone is not empty:
            profile.phone = phone
        profile.save()
        return instance


class SetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(min_length=8)

    def validate_new_password(self, password):
        try:
            validate_password(password)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return password


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate(self, data):
        user = self.context["request"].user
        if not user.check_password(data["current_password"]):
            raise serializers.ValidationError({"current_password": "Your current password is incorrect."})
        try:
            validate_password(data["new_password"], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"new_password": list(error.messages)})
        return data
