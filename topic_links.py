"""Conservative, local Arabic topic links; no paid models or invented summaries."""
import collections,math,re

STOP=set('في من علي على عن الي الى ان وان هذا هذه الذي التي مع بعد قبل خلال بين عند منذ كل اي او هو هي هم لا لم لن ما كما قال وقال اليوم السابع رصد شبكة مزيد تابع التفاصيل المزيد عاجل بالصور بالفيديو اخبار خبر شاهد موقع رابط فقط تابعونا للتفاصيل ايضا واضاف اكد اوضح حيث صباح مساء اهلا سهلا'.split())
ALIASES={'اسعار':'سعر','بنوك':'بنك','مصارف':'بنك','مباريات':'مباراة','اهداف':'هدف','محافظات':'محافظة'}
GENERIC=set('مصر محمد اليوم الجمعه الجمعة الخميس الله ترند عاجل'.split())

def clean(text):
 text=re.sub(r'https?://\S+',' ',text or '')
 text=re.sub(r'[\u064b-\u065f\u0670\u0640]','',text).replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ى','ي')
 return ' '.join(re.findall(r'[a-z\u0621-\u064a]{2,}',text.lower().replace('_',' ')))

def stem(word):
 if word.startswith('وال') and len(word)>5:word=word[1:]
 if word.startswith('ال') and len(word)>4:word=word[2:]
 return ALIASES.get(word,word)

def signal_matches(text,signal):
 label=clean(signal.get('name',''));words=[w for w in label.split() if w not in STOP]
 if not words or (len(words)==1 and (len(words[0])<4 or words[0] in GENERIC)):return False
 return ' '+label+' ' in ' '+clean(text)+' '

def headline(text):
 text=re.sub(r'https?://\S+|#[\w\u064b-\u065f]+','',text or '')
 return ' '.join(text.split()[:12]).strip(' |—:-')[:140]

def link_topics(posts,signals=()):
 rows=[p for p in posts if p.get('text')];texts=[clean(p['text']) for p in rows]
 counts=[];grams=[];labels={}
 for text in texts:
  words=text.split();counts.append(collections.Counter(stem(w) for w in words if w not in STOP))
  phrases=set()
  for size in [2,3]:
   for at in range(len(words)-size+1):
    chunk=words[at:at+size]
    if any(w in STOP for w in chunk):continue
    key=' '.join(stem(w) for w in chunk);phrases.add(key);labels.setdefault(key,' '.join(chunk))
  grams.append(phrases)
 df=collections.Counter(w for row in counts for w in row);vectors=[]
 for row in counts:
  vector={w:(1+math.log(count))*(1+math.log((len(rows)+1)/(df[w]+1))) for w,count in row.items()}
  length=math.sqrt(sum(x*x for x in vector.values())) or 1;vectors.append({w:v/length for w,v in vector.items()})
 anchors=[]
 for item in signals:
  label=clean(item.get('name',''));words=[w for w in label.split() if w not in STOP]
  if not words or (len(words)==1 and (len(words[0])<4 or words[0] in GENERIC)):continue
  hits={i for i,text in enumerate(texts) if ' '+label+' ' in ' '+text+' '}
  if len(hits)>=2:anchors.append({'name':item['name'],'platform':item.get('platform'),'hits':hits})
 pairs={}
 for a in range(len(rows)):
  for b in range(a+1,len(rows)):
   common=set(vectors[a])&set(vectors[b]);cosine=sum(vectors[a][w]*vectors[b][w] for w in common)
   anchored=any(a in x['hits'] and b in x['hits'] for x in anchors)
   related=anchored or (len(common)>=3 and cosine>=0.28) or (len(common)>=2 and cosine>=0.35 and bool(grams[a]&grams[b]))
   if related:pairs[(a,b)]=cosine+(0.4 if anchored else 0)
 groups=[];used=set()
 for (a,b),score in sorted(pairs.items(),key=lambda x:-x[1]):
  if a in used or b in used:continue
  group=[a,b]
  for candidate in range(len(rows)):
   if candidate in used or candidate in group:continue
   if all(tuple(sorted((candidate,member))) in pairs for member in group):group.append(candidate)
  used.update(group);matched=[x for x in anchors if len(x['hits']&set(group))>=2]
  phrase_counts=collections.Counter(g for i in group for g in grams[i]);candidates=[g for g,n in phrase_counts.items() if n>=2]
  if matched:title=max(matched,key=lambda x:(len(x['hits']&set(group)),len(x['name'])))['name']
  elif candidates:title=labels[max(candidates,key=lambda g:(phrase_counts[g],sum(1+math.log((len(rows)+1)/(df[w]+1)) for w in g.split()),len(g.split())))]
  else:title=' '.join(re.sub(r'https?://\S+','',rows[group[0]]['text']).split()[:10])
  if not title:continue
  evidence=[]
  for i in group:
   p=rows[i]
   evidence.append({'source_id':p['source_id'],'source_name':p['source_name'],'url':p['url'],'headline':headline(p['text'])})
  groups.append({'title':title,'post_count':len(group),'source_count':len({rows[i]['source_id'] for i in group}),'evidence':evidence,'matched_trends':[{'name':x['name'],'platform':x['platform']} for x in matched]})
 return sorted(groups,key=lambda x:(-x['source_count'],-x['post_count'],x['title']))

def all_topics(posts,groups,signals=()):
 result=list(groups);covered={e['url'] for g in groups for e in g['evidence']}
 for p in posts:
  if p['url'] in covered or not p.get('text'):continue
  title=headline(p['text'])
  if not title:continue
  evidence={k:p[k] for k in ['source_id','source_name','url']};evidence['headline']=title
  result.append({'title':title,'post_count':1,'source_count':1,'evidence':[evidence],'matched_trends':[{'name':s['name'],'platform':s.get('platform')} for s in signals if signal_matches(p['text'],s)]})
 return result
