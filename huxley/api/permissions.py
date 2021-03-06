# Copyright (c) 2011-2016 Berkeley Model United Nations. All rights reserved.
# Use of this source code is governed by a BSD License (see LICENSE).

import json

from django.http import QueryDict
from rest_framework import permissions

from huxley.core.models import Assignment, Delegate, Registration


class IsSuperuserOrReadOnly(permissions.BasePermission):
    '''Allow writes if superuser, read-only otherwise.'''

    def has_permission(self, request, view):
        return (request.user.is_superuser or
                request.method in permissions.SAFE_METHODS)


class IsUserOrSuperuser(permissions.BasePermission):
    '''Accept only the users themselves or superusers.'''

    def has_object_permission(self, request, view, obj):
        return request.user.is_superuser or request.user == obj


class IsAdvisorOrSuperuser(permissions.BasePermission):
    '''Accept only the school's advisor or superusers.'''

    def has_object_permission(self, request, view, obj):
        return request.user.is_superuser or request.user == obj.advisor


class IsSchoolAdvisorOrSuperuser(permissions.BasePermission):
    '''Accept only the advisor of the given school_id query param.'''

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        school_id = view.kwargs.get('pk', None)
        user = request.user

        return user_is_advisor(request, view, school_id)


class IsPostOrSuperuserOnly(permissions.BasePermission):
    '''Accept POST (create) requests, superusers-only otherwise.'''

    def has_permission(self, request, view):
        return request.method == 'POST' or request.user.is_superuser


class RegistrationListPermission(permissions.BasePermission):
    '''Accept only when the school of the registration object is the same
       as the school of the user, or is a post, or is the superuser.'''

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        if request.method == 'POST':
            return True

        if request.method in permissions.SAFE_METHODS:
            school_id = request.query_params.get('school_id', -1)
            return user_is_advisor(request, view, school_id)

        return False


class RegistrationDetailPermission(permissions.BasePermission):
    '''Accept only when the school of the registration object is the same as the
       school of the user or is a superuser.'''

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        registration_id = view.kwargs.get('pk', None)
        registration = Registration.objects.get(id=registration_id)
        return user_is_advisor(request, view, registration.school_id)


class IsSchoolAssignmentAdvisorOrSuperuser(permissions.BasePermission):
    '''Accept only the advisor of the given school with a given assignment.'''

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        assignment_id = view.kwargs.get('pk', None)
        assignment = Assignment.objects.get(id=assignment_id)
        user = request.user

        return user_is_advisor(request, view,
                               assignment.registration.school_id)


class AssignmentDetailPermission(permissions.BasePermission):
    '''Accept requests to retrieve an assignment from superusers, the advisor of 
       the assignment's school, the chair of the assignment's committee, and 
       delegates with the assignment. Only allow superusers and advisors to
       update assignments.'''

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        assignment_id = view.kwargs.get('pk', None)
        assignment = Assignment.objects.get(id=assignment_id)
        user = request.user
        method = request.method

        if method != 'GET':
            return user_is_advisor(request, view,
                                   assignment.registration.school_id)

        return (
            user_is_advisor(request, view, assignment.registration.school_id)
            or user_is_chair(request, view, assignment.committee_id) or
            user_is_delegate(request, view, assignment_id, 'assignment'))


class AssignmentListPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            school_id = request.query_params.get('school_id', -1)
            committee_id = request.query_params.get('committee_id', -1)
            return (user_is_chair(request, view, committee_id) or
                    user_is_advisor(request, view, school_id))

        return False


class DelegateDetailPermission(permissions.BasePermission):
    '''Accept requests to retrieve, update, and destroy a delegate from the
       superuser and the advisor of the school of the delegate. Accept requests
       to retrieve and update a delegate from the delegate or the chair of the
       committee of the delegate.'''

    def has_permission(self, request, view):
        user = request.user
        if user.is_superuser:
            return True

        delegate_id = view.kwargs['pk']
        delegate = Delegate.objects.get(id=delegate_id)

        if user_is_advisor(request, view, delegate.school_id):
            return True

        if (delegate.assignment and
                user_is_chair(request, view, delegate.assignment.committee_id)
                and request.method != 'DELETE'):
            return True

        if (user_is_delegate(request, view, delegate_id) and
                request.method != 'DELETE'):
            return True

        return False


class DelegateListPermission(permissions.BasePermission):
    '''Accept requests to create, retrieve, and update delegates in bulk from
       the superuser and from the advisor of the school of the delegates.
       Accept requests to retrieve and update delegates from the chair of the
       committee of the delegates.'''

    def has_permission(self, request, view):
        user = request.user
        if user.is_superuser:
            return True

        if not user.is_authenticated():
            return False

        method = request.method
        if method in permissions.SAFE_METHODS:
            school_id = request.query_params.get('school_id', -1)
            committee_id = request.query_params.get('committee_id', -1)
            return (user_is_chair(request, view, committee_id) or
                    user_is_advisor(request, view, school_id))

        if method == 'POST':
            return user_is_advisor(request, view, request.data['school'])

        if method in ('PUT', 'PATCH'):
            delegate_ids = [delegate['id'] for delegate in request.data]
            delegates = Delegate.objects.filter(id__in=delegate_ids)
            if user.is_chair():
                return not delegates.exclude(
                    assignment__committee_id=user.committee_id).exists()

            if user.is_advisor():
                return not delegates.exclude(school_id=user.school_id).exists()

        return False


class SchoolDetailPermission(permissions.BasePermission):
    '''Accept only the school's advisor, the school's delegates, or 
       superusers to retrieve the school. Accept only superusers and the advisor
       to update the school.'''

    def has_permission(self, request, view):
        user = request.user
        if user.is_superuser:
            return True

        method = request.method
        school_id = view.kwargs.get('pk', None)

        if method == 'GET':
            return (user_is_advisor(request, view, school_id) or
                    user_is_delegate(request, view, school_id, 'school'))

        return user_is_advisor(request, view, school_id)


class DelegateUserPasswordPermission(permissions.BasePermission):
    '''Accept requests to change the password of any delegate advised by the 
       current user.'''

    def has_permission(self, request, view):
        user = request.user
        if user.is_superuser:
            return True

        delegate_id = request.data.get('delegate_id', -1)
        queryset = Delegate.objects.filter(id=delegate_id)
        if queryset.exists():
            delegate = queryset.get(id=delegate_id)
            return user_is_advisor(request, view, delegate.school_id)

        return False


def user_is_advisor(request, view, school_id):
    user = request.user
    return (user.is_authenticated() and user.is_advisor() and
            user.school_id == int(school_id))


def user_is_chair(request, view, committee_id):
    user = request.user
    return (user.is_authenticated() and user.is_chair() and
            user.committee_id == int(committee_id))


def user_is_delegate(request, view, target_id, field=None):
    user = request.user
    if not user.is_authenticated() or not user.is_delegate():
        return False

    if field:
        return getattr(user.delegate, field + '_id', -1) == int(target_id)

    return user.delegate_id == int(target_id)
