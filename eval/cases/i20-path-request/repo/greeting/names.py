def clean_name(name):
    return name.strip("Mr. ")


def greet(name):
    return "Hello " + clean_name(name)
