permit (principal, action, resource)
when { context.srcIp.isInRange(ip("10.0.0.0/8")) };
