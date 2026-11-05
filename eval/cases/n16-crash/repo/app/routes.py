def home(settings):
    return "Welcome"


def about(settings):
    return "About this app"


ROUTES = {"/": home, "/about": about}
