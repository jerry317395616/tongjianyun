app_name = "tongjianyun"
app_title = "\u7ae5\u5065\u4e91"
app_publisher = "Local"
app_description = "\u7ae5\u5065\u4e91 Frappe \u540e\u53f0\u5e94\u7528"
app_email = "admin@example.com"
app_license = "mit"
use_json_request_body = True

app_home = "/desk/\u7ae5\u5065\u4e91"
app_logo_url = "/assets/tongjianyun/images/tongjianyun-logo.svg"

add_to_apps_screen = [
    {
        "name": app_name,
        "title": app_title,
        "route": app_home,
        "logo": app_logo_url,
    }
]

after_migrate = [
    "tongjianyun.meal_attendance_setup.install",
    "tongjianyun.recipe_storage.install",
]
