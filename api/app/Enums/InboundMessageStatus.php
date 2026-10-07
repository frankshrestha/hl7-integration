<?php

namespace App\Enums;

enum InboundMessageStatus: string
{
    case Processing = 'processing';
    case Processed = 'processed';
    case Failed = 'failed';
}
