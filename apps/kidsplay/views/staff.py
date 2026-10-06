"""Staff confirm a code, close a visit, or add a bill bonus."""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.kidsplay import conf
from apps.kidsplay.models import PointsLedger, TableVisit
from apps.kidsplay.services import points, rewards, visits


@staff_member_required
def visit_list(request):
    open_visits = (
        TableVisit.objects.filter(closed_at__isnull=True)
        .select_related("family", "qr_code", "outlet")
        .order_by("-started_at")
    )
    return render(request, "kidsplay/staff/visits.html", {"visits": open_visits})


@staff_member_required
def redeem_page(request):
    return render(request, "kidsplay/staff/redeem.html")


@staff_member_required
@require_POST
def redeem_confirm(request):
    ok, reason = rewards.confirm(request.POST.get("code", ""), request.user)
    return JsonResponse({"ok": ok, "status": reason})


@staff_member_required
@require_POST
def redeem_cancel(request):
    ok, reason = rewards.cancel(request.POST.get("code", ""), request.user)
    return JsonResponse({"ok": ok, "status": reason})


@staff_member_required
@require_POST
def visit_close(request, visit_id):
    visit = TableVisit.objects.filter(pk=visit_id).first()
    if visit is None:
        return JsonResponse({"ok": False}, status=404)
    visits.close_visit(visit)
    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
def visit_bill(request, visit_id):
    visit = TableVisit.objects.filter(pk=visit_id).first()
    if visit is None or visit.bill_bonus_awarded:
        return JsonResponse({"ok": False, "status": "already_awarded"}, status=409)
    kid_id = request.POST.get("kid")
    kid = visit.family.kids.filter(pk=kid_id).first()
    if kid is None:
        return JsonResponse({"ok": False, "status": "no_kid"}, status=400)
    visit.bill_ref = request.POST.get("bill_ref", "")[:40]
    visit.bill_bonus_awarded = True
    visit.save(update_fields=["bill_ref", "bill_bonus_awarded"])
    points.award(
        kid,
        conf.get("BILL_BONUS_POINTS"),
        PointsLedger.Reason.BILL_BONUS,
        "TableVisit",
        str(visit.pk),
        created_by=request.user,
    )
    return JsonResponse({"ok": True, "points": conf.get("BILL_BONUS_POINTS")})
