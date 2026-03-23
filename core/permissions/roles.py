from rest_framework.permissions import BasePermission

class IsOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == "OWNER"


class IsAdminOrOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ["ADMIN", "OWNER"]
    
class IsEmployee(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == "EMPLOYEE"