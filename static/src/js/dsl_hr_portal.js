/** @odoo-module **/

(function () {
    "use strict";

    function ready(callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback);
        } else {
            callback();
        }
    }

    function showAlert(app, message, kind) {
        const alertBox = app.querySelector(".dsl-js-alert");
        if (!alertBox) {
            return;
        }
        alertBox.textContent = message;
        alertBox.className = `dsl-js-alert is-visible is-${kind || "info"}`;
        window.clearTimeout(alertBox._dslTimer);
        alertBox._dslTimer = window.setTimeout(() => {
            alertBox.className = "dsl-js-alert";
            alertBox.textContent = "";
        }, 4500);
    }

    function submitPunch(app, button, latitude, longitude) {
        const formData = new FormData();
        formData.append("csrf_token", app.dataset.csrfToken || "");
        formData.append("action", button.dataset.dslPunch);
        formData.append("latitude", latitude);
        formData.append("longitude", longitude);

        return fetch("/dsl/attendance/punch", {
            method: "POST",
            credentials: "same-origin",
            body: formData,
        }).then((response) => response.json());
    }

    ready(function () {
        const app = document.querySelector(".dsl-portal-app");
        if (!app) {
            return;
        }

        document.querySelectorAll("[data-dsl-punch]").forEach((button) => {
            button.addEventListener("click", function () {
                if (button.disabled) {
                    return;
                }
                if (!navigator.geolocation) {
                    showAlert(app, "Location is not available in this browser.", "error");
                    return;
                }

                button.disabled = true;
                const originalText = button.innerHTML;
                button.innerHTML = '<i class="fa fa-spinner fa-spin"></i><span>Locating</span>';

                navigator.geolocation.getCurrentPosition(
                    function (position) {
                        submitPunch(
                            app,
                            button,
                            position.coords.latitude,
                            position.coords.longitude
                        )
                            .then((payload) => {
                                if (payload.ok) {
                                    showAlert(app, payload.message, "success");
                                    window.setTimeout(() => window.location.reload(), 700);
                                } else {
                                    showAlert(app, payload.message || "Attendance was not saved.", "error");
                                }
                            })
                            .catch(() => {
                                showAlert(app, "Attendance was not saved.", "error");
                            })
                            .finally(() => {
                                button.disabled = false;
                                button.innerHTML = originalText;
                            });
                    },
                    function () {
                        showAlert(app, "Location permission is required.", "error");
                        button.disabled = false;
                        button.innerHTML = originalText;
                    },
                    {
                        enableHighAccuracy: true,
                        timeout: 12000,
                        maximumAge: 0,
                    }
                );
            });
        });
    });
})();
