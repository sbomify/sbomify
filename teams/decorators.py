# from functools import wraps

# from django.http import HttpResponseForbidden

# from core.errors import error_response


# def validate_role_in_current_team(allowed_roles):
#     """
#     Verify that a user is logged in and current logged in user has one of the given roles
#     within the team.
#     """

#     def _decorator(function):
#         @wraps(function)
#         def _wrapped_view(request, *args, **kwargs):
#             if not request.user.is_authenticated:
#                 return error_response(request, HttpResponseForbidden("Not logged in"))

#             # TODO: Implement this
#             # Get user role in current team
#             team_id: int | None = request.session.get("current_team", {}).get("id", None)
#             if team_id is None:
#                 return error_response(request, HttpResponseForbidden("No crruent team selected"))

#             if team_id not in request.session.get("user_teams", {}):
#                 return error_response(request, HttpResponseForbidden("Unknown team"))

#             if request.session["user_teams"][team_id]["role"] not in allowed_roles:
#                 return error_response(
#                     request,
#                     HttpResponseForbidden(
#                         "You don't have sufficient permissions to access this page"
#                     ),
#                 )

#             return function(request, *args, **kwargs)

#         return _wrapped_view

#     return _decorator
