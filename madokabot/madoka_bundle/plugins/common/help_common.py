from . import __plugin_meta__
from .matchers import help_common_cmd


@help_common_cmd.handle()
async def handle_help_base():
    await help_common_cmd.finish(__plugin_meta__.usage)
