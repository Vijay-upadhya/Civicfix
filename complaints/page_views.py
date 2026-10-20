from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def landing(request):
    return render(request, "landing.html")


def explore(request):
    return render(request, "explore.html")


def how_it_works(request):
    return render(request, "landing.html", {"anchor": "how"})


def static_page(template):
    def view(request):
        return render(request, template)
    return view


def login_page(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        ident = request.POST.get("email", "").strip().lower()
        user = authenticate(request, username=ident, password=request.POST.get("password", ""))
        if user:
            login(request, user)
            return redirect(request.GET.get("next") or "dashboard")
        messages.error(request, "Incorrect email or password.")
    return render(request, "login.html")


def register_page(request):
    return render(request, "register.html")


@login_required
def dashboard(request):
    return render(request, "dashboard.html")


@login_required
def report(request):
    return render(request, "report.html")


@login_required
def complaint_detail(request, pk):
    return render(request, "complaint_detail.html", {"complaint_id": pk})


@login_required
def notifications_page(request):
    return render(request, "notifications.html")


@login_required
def profile_page(request):
    return render(request, "profile.html")
