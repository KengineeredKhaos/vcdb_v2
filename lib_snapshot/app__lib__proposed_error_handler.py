from flask import jsonify, render_template, request

from app.lib.errors import AppError


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        app.logger.warning(
            {"event": "app_error", **err.to_dict()},
            exc_info=err.cause is not None,
        )

        # Simple heuristic: API routes under /api return JSON; others render page
        wants_json = (
            request.accept_mimetypes.best == "application/json"
            or request.path.startswith("/api")
        )
        status = err.status or 500

        if wants_json:
            return jsonify(err.to_dict()), status

        # For HTML, use a generic template. You can map codes to nicer pages later.
        return render_template("error.html", error=err), status
