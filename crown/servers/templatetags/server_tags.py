from django import template

register = template.Library()


@register.filter
def uptime_fmt(seconds):
    """Format uptime seconds to human readable string."""
    if not seconds:
        return '-'
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@register.filter
def bar_color(value, metric_type='cpu'):
    """Return tailwind color class based on value and metric type."""
    if value is None:
        return 'bg-gray-700'
    value = float(value)
    if value > 90:
        return 'bg-red-500'
    if value > 70:
        return 'bg-yellow-500'
    colors = {'cpu': 'bg-green-500', 'mem': 'bg-blue-500', 'disk': 'bg-purple-500'}
    return colors.get(metric_type, 'bg-green-500')
