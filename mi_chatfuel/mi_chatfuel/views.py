
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

def home(request):
    """
    Redirige a los usuarios autenticados al panel y a los no autenticados
    a la página de login.
    """
    if request.user.is_authenticated:
        return redirect('bots:panel')
    return redirect('login')


@login_required
def logout_view(request):
    """Finaliza la sesión del usuario y lo envía a la pantalla de login."""
    logout(request)
    return redirect('login')
