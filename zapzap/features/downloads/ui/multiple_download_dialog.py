"""Chrome-like protection for repeated automatic download requests."""

from gettext import gettext as _

from PyQt6.QtWidgets import QMessageBox


class MultipleDownloadDecision:
    ALLOW_ONCE = "allow_once"
    ALWAYS_ALLOW = "always_allow"
    BLOCK = "block"


class MultipleDownloadDialog:
    """Ask before a site starts repeated downloads."""

    @staticmethod
    def ask(site: str, parent=None) -> str:
        message = QMessageBox(parent)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle(_("Multiple downloads"))
        message.setText(
            _("{site} wants to download multiple files.").format(site=site)
        )
        message.setInformativeText(
            _("Do you want to allow these additional downloads?")
        )

        allow_once = message.addButton(
            _("Allow once"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        always_allow = message.addButton(
            _("Always allow"),
            QMessageBox.ButtonRole.YesRole,
        )
        block = message.addButton(
            _("Block"),
            QMessageBox.ButtonRole.RejectRole,
        )
        message.setDefaultButton(block)
        message.setEscapeButton(block)
        message.exec()

        clicked = message.clickedButton()
        if clicked is always_allow:
            return MultipleDownloadDecision.ALWAYS_ALLOW
        if clicked is allow_once:
            return MultipleDownloadDecision.ALLOW_ONCE
        return MultipleDownloadDecision.BLOCK
