from signup.validation import is_adult, valid_name


def check_signup(form):
    errors = []
    if not valid_name(form.get("name", "")):
        errors.append("Please enter your name")
    if not is_adult(int(form.get("age", 0))):
        errors.append("You must be an adult to sign up")
    return errors
