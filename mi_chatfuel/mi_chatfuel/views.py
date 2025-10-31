
from django.shortcuts import redirect

def home(request):
    """
    Redirige a los usuarios autenticados al panel y a los no autenticados
    a la página de login.
    """
    if request.user.is_authenticated:
        return redirect('bots:panel')
    return redirect('login')
