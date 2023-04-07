from jinja2 import Environment, PackageLoader, Template

jinja_env = Environment(loader=PackageLoader("bot"))
JINJA_TEMPLATES: dict[str, Template] = {
    "malicious_pypi_package_email": jinja_env.get_template("malicious_pypi_package_email.jinja2")
}
